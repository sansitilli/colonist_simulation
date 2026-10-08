from __future__ import annotations

import json
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .cards import Cards
from .constants import NAME, RESOURCES
from .engine import Branch, Engine, Outcome
from .policy import make_policy
from .replay import Replay, load


@dataclass
class Scenario:
    replay: Replay
    hero: int
    decision_start: int
    decision_end: int
    branches: list[Branch]
    policy: dict
    opponent_policy: dict
    runs: int = 500
    seed: int = 0
    deck_mode: str = "positional"
    known_dev_order: list[int] | None = None
    continue_turns: int = 160
    source: Path | None = None


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path)
    spec = json.loads(path.read_text())
    replay = load((path.parent / spec["replay"]).resolve())
    decision = spec["decision"]
    branches = [
        Branch(
            name=name,
            roads=[tuple(r) for r in b.get("roads", [])],
            settlements=list(b.get("settlements", [b["settlement"]] if "settlement" in b else [])),
            cities=list(b.get("cities", [])),
        )
        for name, b in spec["branches"].items()
    ]
    deck = spec.get("deck", {})
    return Scenario(
        replay=replay,
        hero=replay.color_of(spec["hero"]),
        decision_start=int(decision["start"]),
        decision_end=int(decision.get("end", decision["start"])),
        branches=branches,
        policy=spec.get("policy", {"name": "adaptive"}),
        opponent_policy=spec.get("opponent_policy", {"name": "adaptive"}),
        runs=int(spec.get("runs", 500)),
        seed=int(spec.get("seed", 0)),
        deck_mode=deck.get("mode", "positional"),
        known_dev_order=deck.get("known_order"),
        continue_turns=int(spec.get("continue_turns", 160)),
        source=path,
    )


def make_engine(sc: Scenario, branch: Branch, seed: int, policy: dict | None = None) -> Engine:
    return Engine(
        sc.replay,
        sc.hero,
        sc.decision_start,
        branch,
        make_policy(policy or sc.policy, sc.replay, sc.hero, sc.decision_end),
        seed=seed,
        deck_mode=sc.deck_mode,
        known_dev_order=sc.known_dev_order,
        continue_turns=sc.continue_turns,
        opponent_policy=sc.opponent_policy,
    )


def simulate(
    sc: Scenario,
    branch: Branch,
    seed: int,
    from_decision: bool = False,
    policy: dict | None = None,
    random_dice: bool = False,
) -> Outcome:
    engine = make_engine(sc, branch, seed, policy)
    if from_decision:
        return engine.run_from_decision(recorded_dice=not random_dice)
    return engine.run()


@dataclass
class Summary:
    branch: str
    runs: int
    hero_win: float
    hero_win_in_record: float
    winners: Counter
    hero_win_turns: Counter
    mean_hero_win_turn: float | None
    median_hero_win_turn: float | None
    mean_game_end: float
    trade_usage: dict[str, float]
    mean_produced: dict[str, float]
    mean_lost: dict[str, float]
    issues: Counter
    outcomes: list[Outcome] = field(default_factory=list, repr=False)


def summarize(outcomes: list[Outcome]) -> Summary:
    n = len(outcomes)
    wins = [o.win_turn for o in outcomes if o.win_turn is not None]
    produced, lost = Cards(), Cards()
    trades: Counter = Counter()
    issues: Counter = Counter()
    for o in outcomes:
        produced += o.produced
        lost += o.lost
        for _, t in o.trades:
            trades[f"{t.ratio}:1 {NAME[t.give]}"] += 1
        for i in {x.split(": ", 1)[1] if ": " in x else x for x in o.issues}:
            issues[i] += 1
    ends = [o.winner_turn for o in outcomes if o.winner_turn is not None]
    return Summary(
        branch=outcomes[0].branch,
        runs=n,
        hero_win=len(wins) / n,
        hero_win_in_record=sum(1 for o in outcomes if o.won_in_record) / n,
        winners=Counter(o.winner for o in outcomes),
        hero_win_turns=Counter(wins),
        mean_hero_win_turn=statistics.fmean(wins) if wins else None,
        median_hero_win_turn=statistics.median(wins) if wins else None,
        mean_game_end=statistics.fmean(ends) if ends else float("nan"),
        trade_usage={k: v / n for k, v in sorted(trades.items())},
        mean_produced={NAME[r]: round(produced[r] / n, 2) for r in RESOURCES},
        mean_lost={NAME[r]: round(lost[r] / n, 2) for r in RESOURCES},
        issues=issues,
        outcomes=outcomes,
    )


def run_scenario(
    sc: Scenario, runs: int | None = None, from_decision: bool = False, random_dice: bool = False
) -> dict[str, Summary]:
    runs = runs or sc.runs
    return {
        b.name: summarize(
            [simulate(sc, b, sc.seed + i, from_decision, random_dice=random_dice) for i in range(runs)]
        )
        for b in sc.branches
    }


def paired(a: Summary, b: Summary) -> dict[str, float]:
    both = flip_to_b = flip_to_a = neither = 0
    for x, y in zip(a.outcomes, b.outcomes):
        wx, wy = x.win_turn is not None, y.win_turn is not None
        if wx and wy:
            both += 1
        elif wy:
            flip_to_b += 1
        elif wx:
            flip_to_a += 1
        else:
            neither += 1
    n = len(a.outcomes)
    return {"both_win": both / n, "only_b_wins": flip_to_b / n, "only_a_wins": flip_to_a / n, "neither": neither / n}
