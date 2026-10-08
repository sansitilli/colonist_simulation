from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from .cards import Cards
from .constants import COST, RESOURCES, DevCard
from .engine import Branch, Engine, HeroView
from .policy import GreedyPolicy, Policy
from .scenario import Scenario

_DEV_VALUE = {
    DevCard.MONOPOLY: 2.0,
    DevCard.YEAR_OF_PLENTY: 1.5,
    DevCard.ROAD_BUILDING: 0.5,
    DevCard.KNIGHT: 0.5,
    DevCard.VICTORY_POINT: 0.0,
}

_KEEP_TARGETS = (
    ("city",),
    ("dev",),
    ("city", "dev"),
    ("city", "city"),
    ("dev", "dev"),
    ("settlement",),
    ("settlement", "dev"),
)


class _Unused(Policy):
    name = "oracle"

    def __init__(self):
        super().__init__()
        self.helper = GreedyPolicy()

    def upcoming(self, view):
        return self.helper.upcoming(view)

    def purchase(self, view) -> None:
        pass


@dataclass
class OracleResult:
    branch: str
    seed: int
    win_turn: int | None
    best_vp: int
    horizon: int
    line: list[str] = field(default_factory=list)
    expanded: int = 0


def _signature(e: Engine) -> tuple:
    return (
        tuple(e.hand.v),
        tuple(sorted(e.hero_corners.items())),
        tuple(sorted(e.hero_roads)),
        tuple(sorted((int(c), t < e.turn) for c, t in e.dev_hand)),
        e.vp_cards,
        e.knights,
        e.deck.hero_drawn,
        tuple(tuple(e.adj[p].v) for p in e.opponents),
        e.robber_override,
    )


def _score(e: Engine) -> float:
    hand = e.hand
    ratios = e.ratios()
    best = 0.0
    for kind in ("city", "dev", "settlement"):
        need = Cards(COST[kind])
        covered = sum(min(hand[r], need[r]) for r in RESOURCES)
        spare = hand.surplus(need)
        convert = sum(spare[r] // ratios[r] for r in RESOURCES)
        best = max(best, min(1.0, (covered + convert) / need.total()))
    liquidity = sum(hand[r] / ratios[r] for r in RESOURCES)
    devs = sum(_DEV_VALUE.get(c, 0.0) for c, _ in e.dev_hand)
    production = 0.0
    for c, kind in e.hero_corners.items():
        production += e.board.corner_pips(c) * (2 if kind == "city" else 1)
    return e.vp() * 10 + 3 * best + 0.4 * liquidity + devs + 0.05 * production


def _dev_options(e: Engine) -> list[tuple]:
    opts: list[tuple] = [()]
    if e.playable(DevCard.MONOPOLY):
        for r in RESOURCES:
            if sum(max(0, e.opp_hand(p)[r]) for p in e.opponents) > 0:
                opts.append(("monopoly", r))
    if e.playable(DevCard.YEAR_OF_PLENTY):
        bank = e.bank()
        for a, b in itertools.combinations_with_replacement(RESOURCES, 2):
            if bank[a] >= (2 if a == b else 1) and bank[b] >= 1:
                opts.append(("yop", a, b))
    if e.playable(DevCard.KNIGHT):
        opts.append(("knight",))
    if e.playable(DevCard.ROAD_BUILDING) and e.pieces_left("settlement") > 0:
        paths = [p for _, p in e.settlement_options(2) if p]
        if paths:
            opts.append(("road_building",))
    return opts


def _apply_dev(e: Engine, opt: tuple) -> bool:
    if not opt:
        return True
    kind = opt[0]
    if kind == "monopoly":
        e.play_monopoly(opt[1])
    elif kind == "yop":
        e.play_year_of_plenty(opt[1], opt[2])
    elif kind == "knight":
        e.play_knight()
    elif kind == "road_building":
        options = [o for o in e.settlement_options(2) if o[1]]
        corner, path = max(options, key=lambda o: (e.board.corner_pips(o[0]), -len(o[1])))
        e.play_road_building(path[:2])
    return True


def _purchase_types(e: Engine, settle_width: int) -> list[tuple]:
    types: list[tuple] = []
    if e.pieces_left("city") > 0:
        for c, k in sorted(e.hero_corners.items()):
            if k == "settlement":
                types.append((0, c, "city"))
    if e.pieces_left("settlement") > 0:
        spots = sorted(
            e.settlement_options(2),
            key=lambda o: (-(e.board.corner_pips(o[0]) - 2 * len(o[1])), len(o[1]), o[0]),
        )[:settle_width]
        for c, path in spots:
            types.append((1, c, "settlement", tuple(path)))
    if e.deck.remaining() > 0:
        types.append((2, 0, "dev"))
    return types


def _apply_purchase(e: Engine, t: tuple) -> bool:
    if t[2] == "city":
        return e.build_city(t[1])
    if t[2] == "settlement":
        return e.build_settlement(t[1], list(t[3]))
    return e.buy_dev()


def _purchase_leaves(e: Engine, last: tuple, settle_width: int, out: list[Engine], depth: int = 0) -> None:
    out.append(e)
    if depth >= 6:
        return
    for t in _purchase_types(e, settle_width):
        if t[:2] < last[:2]:
            continue
        need = Cards(COST[t[2]])
        if t[2] == "settlement":
            for _ in t[3]:
                need += Cards(COST["road"])
        if e.plan(need) is None:
            continue
        child = e.clone()
        if _apply_purchase(child, t):
            _purchase_leaves(child, t, settle_width, out, depth + 1)


def _trade_down(e: Engine) -> Engine | None:
    if e.hand.total() <= 7:
        return None
    child = e.clone()
    child.policy.helper.manage_hand(_view(child))
    return child if child.hand.total() < e.hand.total() else None


def _view(e: Engine) -> HeroView:
    return HeroView(e)


def _discard_options(e: Engine, n: int) -> list[Cards]:
    hand = e.hand
    seen: set[tuple] = set()
    out: list[Cards] = []
    for target in _KEEP_TARGETS:
        need = Cards()
        for k in target:
            need += Cards(COST[k])
        keep = Cards(min(hand[r], need[r]) for r in RESOURCES)
        ratios = e.ratios()
        rest = hand - keep
        keep_n = hand.total() - n
        while keep.total() > keep_n:
            r = max((r for r in RESOURCES if keep[r] > 0), key=lambda r: keep[r] - need[r] / 10)
            keep.add(r, -1)
        while keep.total() < keep_n:
            r = min((r for r in RESOURCES if rest[r] > 0), key=lambda r: (ratios[r], -rest[r]))
            rest.add(r, -1)
            keep.add(r, 1)
        d = hand - keep
        if d.total() == n and tuple(d.v) not in seen:
            seen.add(tuple(d.v))
            out.append(d)
    heuristic = e.policy.helper.discard(_view(e), n)
    if tuple(heuristic.v) not in seen:
        out.append(heuristic)
    return out


def _advance_all(states: list[Engine], beam: int) -> list[Engine]:
    ready: list[Engine] = []
    work = list(states)
    while work:
        nxt: list[Engine] = []
        for e in work:
            status = e.advance()
            if status == "turn":
                ready.append(e)
            elif status == "discard":
                n = e.discard_due
                options = _discard_options(e, n)
                for i, d in enumerate(options):
                    child = e if i == len(options) - 1 else e.clone()
                    child.apply_discard(d)
                    nxt.append(child)
            elif status == "lost":
                continue
            else:
                e._exhausted = True
                ready.append(e)
        work = _prune(nxt, beam * 3)
    return ready


def _prune(states: list[Engine], width: int) -> list[Engine]:
    seen: dict[tuple, Engine] = {}
    for e in states:
        sig = _signature(e)
        if sig not in seen:
            seen[sig] = e
    ranked = sorted(seen.values(), key=_score, reverse=True)
    return ranked[:width]


def search(sc: Scenario, branch: Branch, seed: int, beam: int = 150, settle_width: int = 2) -> OracleResult:
    root = Engine(
        sc.replay,
        sc.hero,
        sc.decision_start,
        branch,
        _Unused(),
        seed=seed,
        deck_mode=sc.deck_mode,
        known_dev_order=sc.known_dev_order,
    )
    root.begin()
    root._exhausted = False
    frontier = _advance_all([root], beam)
    best_vp = root.vp()
    expanded = 0
    while frontier:
        leaves: list[Engine] = []
        for e in frontier:
            if getattr(e, "_exhausted", False):
                continue
            for opt in _dev_options(e):
                child = e.clone()
                _apply_dev(child, opt)
                bucket: list[Engine] = []
                _purchase_leaves(child, (-1, -1), settle_width, bucket)
                for leaf in bucket:
                    leaves.append(leaf)
                    down = _trade_down(leaf)
                    if down is not None:
                        leaves.append(down)
        expanded += len(leaves)
        if not leaves:
            break
        winners = []
        for leaf in leaves:
            leaf.end_turn()
            best_vp = max(best_vp, leaf.vp())
            if leaf.won_turn is not None:
                winners.append(leaf)
        if winners:
            w = max(winners, key=_score)
            return OracleResult(branch.name, seed, w.won_turn, w.vp(), w.won_turn, w.log, expanded)
        frontier = _advance_all(_prune(leaves, beam), beam)
        frontier = [e for e in frontier if not getattr(e, "_exhausted", False)]
    best = max(leaves, key=_score) if leaves else root
    return OracleResult(branch.name, seed, None, best_vp, sc.replay.events[-1].turn, best.log, expanded)
