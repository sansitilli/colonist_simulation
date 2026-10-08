from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .anonymize import anonymize
from .audit import audit
from .board import GENERIC_PORT
from .constants import NAME, Resource
from .engine import Branch, Engine
from .oracle import search
from .policy import GreedyPolicy
from .replay import Build, load
from .scenario import Scenario, load_scenario, paired, run_scenario, simulate


def _table(rows: list[list], header: list[str]) -> str:
    cells = [header] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(header))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def cmd_inspect(args) -> int:
    r = load(args.replay)
    print(f"game {r.game_id}: {r.total_turns} turns, winner {r.name(r.winner) if r.winner else '-'}")
    print(_table([[c, r.name(c)] for c in r.play_order], ["color", "player"]))
    print()
    tiles = [[t.index, t.q, t.r, t.label(), t.pips] for t in sorted(r.board.tiles.values(), key=lambda t: (t.r, t.q))]
    print(_table(tiles, ["tile", "q", "r", "hex", "pips"]))
    print()
    ports: dict[int, list[int]] = {}
    for c, p in r.board.corner_ports.items():
        ports.setdefault(p, []).append(c)
    rows = []
    for p, cs in sorted(ports.items()):
        label = "3:1" if p == GENERIC_PORT else f"{NAME[Resource(p)]} 2:1"
        rows.append([label, " ".join(map(str, sorted(cs)))])
    print(_table(rows, ["port", "corners"]))
    print()
    print(f"dev draw order: {[c.name.lower() for c in r.dev_draw_order]}")
    if args.player:
        color = r.color_of(args.player)
        print()
        rows = []
        for ev in r.events:
            for a in ev.actions:
                if isinstance(a, Build) and a.player == color:
                    where = r.board.edge_corners.get(a.location) if a.piece == "road" else r.board.corner_label(a.location)
                    rows.append([ev.index, ev.turn, a.piece, a.location, where])
        print(_table(rows, ["event", "turn", "piece", "id", "location"]))
    return 0


def cmd_anonymize(args) -> int:
    renamed = anonymize(args.source, args.target, args.keep)
    for old, new in renamed.items():
        print(f"{old} -> {new}")
    print(f"chat, user ids and country codes removed; written to {args.target}")
    return 0


def cmd_audit(args) -> int:
    r = load(args.replay)
    status = 0
    for color in r.play_order:
        rep = audit(r, color)
        print(
            f"{r.name(color):<14} snapshots {rep.snapshots:>3}  rolls {rep.rolls:>3}  dev draws {rep.dev_checked:>2}  "
            f"{'OK' if rep.ok else 'MISMATCH'}"
        )
        for line in (rep.hand_mismatches + rep.production_mismatches + rep.dev_mismatches)[:10]:
            print("   ", line)
        status |= 0 if rep.ok else 1
    return status


def cmd_candidates(args) -> int:
    r = load(args.replay)
    color = r.color_of(args.player)
    e = Engine(r, color, args.event, Branch("probe"), GreedyPolicy())
    print(f"{r.name(color)} at event {args.event} (turn {e.turn}), hand {e.hand}, ratios "
          + " ".join(f"{NAME[k][0].upper()}{v}" for k, v in e.ratios().items()))
    rows = []
    for c, path in sorted(e.settlement_options(args.roads), key=lambda o: (len(o[1]), -r.board.corner_pips(o[0]))):
        roads = " ".join(f"{a}-{b}" for a, b in (r.board.edge_corners[x] for x in path)) or "-"
        rows.append([c, r.board.corner_pips(c), len(path), roads, r.board.corner_label(c)])
    print(_table(rows, ["corner", "pips", "roads", "road path", "hexes / port"]))
    return 0


def _apply_overrides(sc: Scenario, args) -> None:
    if getattr(args, "deck", None):
        sc.deck_mode = args.deck
    if getattr(args, "policy", None):
        sc.policy = {**sc.policy, "name": args.policy}


def _turns(c: Counter, limit: int = 8) -> str:
    return " ".join(f"t{k}:{v}" for k, v in sorted(c.items())[:limit]) or "-"


def cmd_run(args) -> int:
    sc = load_scenario(args.scenario)
    _apply_overrides(sc, args)
    runs = args.runs or sc.runs
    out = run_scenario(sc, runs=runs, from_decision=args.from_decision, random_dice=args.random_dice)
    r = sc.replay
    last = r.events[-1].turn
    if not args.from_decision:
        start = f"opponents follow the record; recorded dice to turn {last}, random after"
    elif args.random_dice:
        start = "everyone adaptive from the decision; random dice from the decision"
    else:
        start = f"everyone adaptive from the decision; recorded dice to turn {last}, random after"
    print(f"{start}; deck {sc.deck_mode}; hero {sc.policy.get('name')}, opponents {sc.opponent_policy.get('name')}; {runs} runs")
    rows = []
    report: dict = {
        "runs": runs,
        "deck": sc.deck_mode,
        "from_decision": args.from_decision,
        "random_dice": args.random_dice,
        "branches": {},
    }
    for name, sm in out.items():
        winners = " ".join(f"{r.name(p) if p else 'none'} {n / sm.runs:.1%}" for p, n in sm.winners.most_common())
        rows.append([
            name,
            f"{sm.hero_win:.1%}",
            f"{sm.hero_win_in_record:.1%}",
            f"{sm.mean_hero_win_turn:.1f}" if sm.mean_hero_win_turn else "-",
            winners,
        ])
        report["branches"][name] = {
            "hero_win": sm.hero_win,
            "hero_win_by_turn_77": sm.hero_win_in_record,
            "winners": {r.name(p) if p else "none": n / sm.runs for p, n in sm.winners.items()},
            "hero_win_turns": dict(sorted(sm.hero_win_turns.items())),
            "mean_hero_win_turn": sm.mean_hero_win_turn,
            "trade_usage_per_run": sm.trade_usage,
            "mean_cards_produced": sm.mean_produced,
            "mean_cards_lost": sm.mean_lost,
            "consistency_notes": dict(sm.issues),
        }
    print()
    print(_table(rows, ["branch", "hero wins", "within record", "mean win turn", "winner share"]))
    names = list(out)
    for other in names[1:]:
        pr = paired(out[names[0]], out[other])
        print(
            f"\npaired seeds, {other} vs {names[0]}: both win {pr['both_win']:.1%}, "
            f"only {other} {pr['only_b_wins']:.1%}, only {names[0]} {pr['only_a_wins']:.1%}, neither {pr['neither']:.1%}"
        )
        report[f"{other}_vs_{names[0]}"] = pr
    for name, sm in out.items():
        print(f"\n{name}: hero win turns {_turns(sm.hero_win_turns)}")
        print("  trades per run: " + (", ".join(f"{k} x{v:.2f}" for k, v in sm.trade_usage.items()) or "-"))
        for k, v in sm.issues.most_common(4):
            print(f"  note in {v / sm.runs:.0%} of runs: {k}")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str))
    return 0


def cmd_oracle(args) -> int:
    sc = load_scenario(args.scenario)
    _apply_overrides(sc, args)
    rows = []
    lines = {}
    for b in sc.branches:
        results = [search(sc, b, sc.seed + i, beam=args.beam) for i in range(args.seeds)]
        wins = [x.win_turn for x in results if x.win_turn is not None]
        rows.append([
            b.name,
            f"{len(wins) / len(results):.0%}",
            min(wins) if wins else "-",
            " ".join(f"t{k}:{v}" for k, v in sorted(Counter(wins).items())) or "-",
            max(x.best_vp for x in results),
        ])
        lines[b.name] = results[0]
    print(f"clairvoyant planner within the record, deck {sc.deck_mode}, beam {args.beam}, {args.seeds} seeds")
    print(_table(rows, ["branch", "wins by turn 77", "earliest", "win turns", "best VP"]))
    if args.show_line:
        for name, res in lines.items():
            print(f"\n{name} (seed {res.seed}):")
            for line in res.line:
                print("  " + line)
    return 0


def cmd_trace(args) -> int:
    sc = load_scenario(args.scenario)
    _apply_overrides(sc, args)
    branch = next((b for b in sc.branches if b.name == args.branch), None)
    if branch is None:
        print(f"unknown branch {args.branch}; choose from {[b.name for b in sc.branches]}", file=sys.stderr)
        return 2
    if args.oracle:
        res = search(sc, branch, args.seed, beam=args.beam)
        print(f"{branch.name}: clairvoyant win turn {res.win_turn}")
        log, issues = res.line, []
    else:
        o = simulate(sc, branch, args.seed, from_decision=args.from_decision, random_dice=args.random_dice)
        who = sc.replay.name(o.winner) if o.winner else "nobody"
        print(f"{branch.name}: {who} wins on turn {o.winner_turn}; final VP "
              + ", ".join(f"{sc.replay.name(p)} {v}" for p, v in o.final_vps.items()))
        log, issues = o.log, o.issues
    for line in log:
        print("  " + line)
    if issues:
        print("consistency notes:")
        for i in sorted(set(issues)):
            print("  " + i)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="colonist-cf", description="Counterfactual replays of Colonist.io games")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inspect", help="board, ports, players and a player's builds")
    p.add_argument("replay")
    p.add_argument("--player")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("anonymize", help="replace usernames with colours and strip chat and account data")
    p.add_argument("source")
    p.add_argument("target")
    p.add_argument("--keep", action="append", default=[], help="username to keep, repeatable")
    p.set_defaults(func=cmd_anonymize)

    p = sub.add_parser("audit", help="rebuild every hand from parsed actions and compare to the replay")
    p.add_argument("replay")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("candidates", help="legal settlement spots for a player at an event")
    p.add_argument("replay")
    p.add_argument("--player", required=True)
    p.add_argument("--event", type=int, required=True)
    p.add_argument("--roads", type=int, default=2)
    p.set_defaults(func=cmd_candidates)

    for name, fn, text in (
        ("run", cmd_run, "Monte Carlo comparison of the branches"),
        ("oracle", cmd_oracle, "earliest win per branch with full knowledge of dice and deck"),
        ("trace", cmd_trace, "turn-by-turn log of a single run"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("scenario")
        p.add_argument("--deck", choices=["queue", "positional"])
        p.add_argument("--policy", choices=["adaptive", "scripted"])
        if name == "run":
            p.add_argument("--runs", type=int)
            p.add_argument("--from-decision", action="store_true", help="every player adaptive from the decision")
            p.add_argument("--random-dice", action="store_true", help="with --from-decision, ignore the recorded dice")
            p.add_argument("--json")
        if name == "oracle":
            p.add_argument("--seeds", type=int, default=20)
            p.add_argument("--beam", type=int, default=150)
            p.add_argument("--show-line", action="store_true")
        if name == "trace":
            p.add_argument("--branch", required=True)
            p.add_argument("--seed", type=int, default=0)
            p.add_argument("--from-decision", action="store_true")
            p.add_argument("--random-dice", action="store_true")
            p.add_argument("--oracle", action="store_true")
            p.add_argument("--beam", type=int, default=150)
        p.set_defaults(func=fn)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
