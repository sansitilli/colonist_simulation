from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from .cards import Cards
from .constants import (
    COST,
    DISCARD_LIMIT,
    PIECE_LIMIT,
    RESOURCES,
    VICTORY_POINTS_TO_WIN,
    DevCard,
    Resource,
)
from .replay import LARGEST_ARMY_KEY
from .trading import Trade, plan_trades

if TYPE_CHECKING:
    from .engine import Engine
    from .policy import Policy

LONGEST_ROAD_KEY = 4
MIN_LONGEST_ROAD = 5
MIN_LARGEST_ARMY = 3


@dataclass
class FullResult:
    winner: int | None
    turn: int
    vp: dict[int, int]
    log: list[str] = field(default_factory=list)


class FullGame:
    def __init__(
        self,
        engine: "Engine",
        policies: dict[int, "Policy"],
        seed: int,
        start_turn: int,
        first: int,
        dice: dict[int, int] | None = None,
    ):
        self.board = engine.board
        self.names = {p: engine.replay.name(p) for p in engine.order}
        self.order = list(engine.order)
        self.hero = engine.hero
        self.policies = policies
        self.rng = random.Random(f"full:{seed}")
        self.dice_rng = random.Random(f"dice:{seed}")
        self.dice = dict(dice or {})
        self.turn = start_turn
        self.idx = self.order.index(first)
        deck = engine.deck
        if deck.mode == "positional":
            self.stack = list(deck.order[deck.position:])
        else:
            self.stack = list(deck._queue[deck.hero_drawn:])
        bank = engine.bank()
        self.bank = {r: max(0, bank[r]) for r in RESOURCES}
        self.robber = engine.effective_robber()
        self.hands: dict[int, Cards] = {}
        self.corners: dict[int, tuple[int, str]] = {}
        self.roads: dict[int, int] = {}
        self.devs: dict[int, list[list]] = {p: [] for p in self.order}
        self.knights: Counter = Counter(engine.opp_knights)
        self.knights[self.hero] = engine.knights
        self.dev_played: dict[int, int] = {}
        self.log: list[str] = []
        self.hero_trades: list[tuple[int, Trade]] = []
        self.hero_produced = Cards()

        for p in self.order:
            self.hands[p] = engine.hand.copy() if p == self.hero else engine.opp_hand(p).clamp()
        for c, kind in engine.hero_corners.items():
            self.corners[c] = (self.hero, kind)
        for c, (p, kind) in engine.opp_corners.items():
            self.corners[c] = (p, kind)
        for e in engine.hero_roads:
            self.roads[e] = self.hero
        for e, p in engine.opp_roads.items():
            self.roads[e] = p
        self.devs[self.hero] = [[c, -1] for c, _ in engine.dev_hand]
        for p in engine.opponents:
            for card, n in engine.opp_devs[p].items():
                self.devs[p].extend([[card, -1] for _ in range(max(0, n))])

        self.army = None
        if engine.hero_has_largest_army():
            self.army = self.hero
        else:
            self.army = next((p for p in engine.opponents if engine.rec_vp[p].get(LARGEST_ARMY_KEY)), None)
        self.road_holder = next(
            (p for p in engine.opponents if engine.rec_vp[p].get(LONGEST_ROAD_KEY)), None
        )
        if self.road_holder is None:
            self._update_longest_road()

    def name(self, p: int) -> str:
        return self.names.get(p, str(p))

    def note(self, text: str) -> None:
        self.log.append(f"t{self.turn}: {text}")

    def owned(self, p: int) -> dict[int, str]:
        return {c: k for c, (o, k) in self.corners.items() if o == p}

    def vp(self, p: int) -> int:
        pts = sum(2 if k == "city" else 1 for k in self.owned(p).values())
        pts += sum(1 for c, _ in self.devs[p] if c == DevCard.VICTORY_POINT)
        if self.army == p:
            pts += 2
        if self.road_holder == p:
            pts += 2
        return pts

    def ratios(self, p: int) -> dict[Resource, int]:
        return self.board.trade_ratios(set(self.owned(p)))

    def adjacent(self, p: int, tile: int) -> bool:
        return any(self.corners.get(c, (None,))[0] == p for c in self.board.tile_corners[tile])

    def road_length(self, p: int) -> int:
        mine = {e for e, o in self.roads.items() if o == p}
        if not mine:
            return 0

        def blocked(c: int) -> bool:
            o = self.corners.get(c)
            return o is not None and o[0] != p

        def walk(c: int, used: frozenset) -> int:
            best = 0
            if blocked(c) and used:
                return 0
            for e in self.board.corner_edges[c]:
                if e in mine and e not in used:
                    a, b = self.board.edge_corners[e]
                    d = b if a == c else a
                    best = max(best, 1 + walk(d, used | {e}))
            return best

        ends = {c for e in mine for c in self.board.edge_corners[e]}
        return max(walk(c, frozenset()) for c in ends)

    def _update_longest_road(self) -> None:
        lengths = {p: self.road_length(p) for p in self.order}
        current = lengths.get(self.road_holder, 0) if self.road_holder is not None else 0
        if self.road_holder is not None and current < MIN_LONGEST_ROAD:
            self.road_holder = None
            current = 0
        for p in self.order:
            if lengths[p] >= MIN_LONGEST_ROAD and lengths[p] > current and p != self.road_holder:
                if self.road_holder is not None:
                    self.note(f"{self.name(p)} takes longest road from {self.name(self.road_holder)}")
                self.road_holder = p
                current = lengths[p]

    def _update_largest_army(self, p: int) -> None:
        held = self.knights[self.army] if self.army is not None else 0
        if self.knights[p] >= MIN_LARGEST_ARMY and self.knights[p] > held and self.army != p:
            self.army = p
            self.note(f"{self.name(p)} takes largest army")

    def settlement_legal(self, p: int, c: int, roads: set[int]) -> bool:
        if c in self.corners or any(n in self.corners for n in self.board.corner_neighbors[c]):
            return False
        return any(e in roads for e in self.board.corner_edges[c])

    def road_legal(self, p: int, e: int) -> bool:
        if e in self.roads:
            return False
        for c in self.board.edge_corners[e]:
            owner = self.corners.get(c)
            if owner is not None and owner[0] == p:
                return True
            if owner is not None:
                continue
            if any(self.roads.get(x) == p for x in self.board.corner_edges[c]):
                return True
        return False

    def settlement_options(self, p: int, max_roads: int) -> list[tuple[int, list[int]]]:
        mine = {e for e, o in self.roads.items() if o == p}
        start = set(self.owned(p))
        for e in mine:
            for c in self.board.edge_corners[e]:
                o = self.corners.get(c)
                if o is None or o[0] == p:
                    start.add(c)
        best = {c: [] for c in start}
        frontier = list(start)
        for _ in range(max_roads):
            nxt = []
            for c in frontier:
                for e in self.board.corner_edges[c]:
                    if e in self.roads:
                        continue
                    a, b = self.board.edge_corners[e]
                    d = b if a == c else a
                    o = self.corners.get(d)
                    if d in best or (o is not None and o[0] != p):
                        continue
                    best[d] = best[c] + [e]
                    nxt.append(d)
            frontier = nxt
        return [(c, path) for c, path in best.items() if self.settlement_legal(p, c, mine | set(path))]

    def pieces_left(self, p: int, kind: str) -> int:
        if kind == "road":
            return PIECE_LIMIT["road"] - sum(1 for o in self.roads.values() if o == p)
        return PIECE_LIMIT[kind] - sum(1 for k in self.owned(p).values() if k == kind)

    def plan(self, p: int, need: Cards, keep=None):
        return plan_trades(self.hands[p], need, self.ratios(p), self.bank, keep)

    def trade(self, p: int, t: Trade) -> None:
        if self.hands[p][t.give] < t.ratio or self.bank[t.get] < 1:
            raise RuntimeError(f"illegal trade {t}")
        self.hands[p].add(t.give, -t.ratio)
        self.hands[p].add(t.get, 1)
        self.bank[t.give] += t.ratio
        self.bank[t.get] -= 1
        if p == self.hero:
            self.hero_trades.append((self.turn, t))

    def pay(self, p: int, need: Cards, keep=None) -> bool:
        trades = self.plan(p, need, keep)
        if trades is None:
            return False
        for t in trades:
            self.trade(p, t)
        self.hands[p] -= need
        for r in RESOURCES:
            self.bank[r] += need[r]
        return True

    def build_road(self, p: int, e: int, free: bool = False, keep=None) -> bool:
        if not self.road_legal(p, e) or self.pieces_left(p, "road") < 1:
            return False
        if not free and not self.pay(p, Cards(COST["road"]), keep):
            return False
        self.roads[e] = p
        self._update_longest_road()
        return True

    def build_settlement(self, p: int, c: int, path=None, keep=None) -> bool:
        path = list(path or [])
        mine = {e for e, o in self.roads.items() if o == p}
        if self.pieces_left(p, "settlement") < 1 or self.pieces_left(p, "road") < len(path):
            return False
        if not self.settlement_legal(p, c, mine | set(path)):
            return False
        total = Cards(COST["settlement"])
        for _ in path:
            total += Cards(COST["road"])
        if not self.pay(p, total, keep):
            return False
        for e in path:
            self.roads[e] = p
        self.corners[c] = (p, "settlement")
        self._update_longest_road()
        self.note(f"{self.name(p)} settlement {c}")
        return True

    def build_city(self, p: int, c: int, keep=None) -> bool:
        if self.corners.get(c) != (p, "settlement") or self.pieces_left(p, "city") < 1:
            return False
        if not self.pay(p, Cards(COST["city"]), keep):
            return False
        self.corners[c] = (p, "city")
        self.note(f"{self.name(p)} city {c}")
        return True

    def buy_dev(self, p: int, keep=None) -> bool:
        if not self.stack:
            return False
        if not self.pay(p, Cards(COST["dev"]), keep):
            return False
        card = self.stack.pop(0)
        self.devs[p].append([card, self.turn])
        self.note(f"{self.name(p)} buys a development card")
        return True

    def playable(self, p: int, card: DevCard) -> bool:
        if self.dev_played.get(p) == self.turn:
            return False
        return any(c == card and t < self.turn for c, t in self.devs[p])

    def _consume(self, p: int, card: DevCard) -> None:
        for i, (c, t) in enumerate(self.devs[p]):
            if c == card and t < self.turn:
                del self.devs[p][i]
                self.dev_played[p] = self.turn
                return
        raise RuntimeError(f"{card} not playable")

    def play_monopoly(self, p: int, r: Resource) -> int:
        self._consume(p, DevCard.MONOPOLY)
        got = 0
        for q in self.order:
            if q != p:
                got += self.hands[q][r]
                self.hands[q][r] = 0
        self.hands[p].add(r, got)
        self.note(f"{self.name(p)} monopoly {r.name.lower()} +{got}")
        return got

    def play_year_of_plenty(self, p: int, a: Resource, b: Resource) -> None:
        self._consume(p, DevCard.YEAR_OF_PLENTY)
        for r in (a, b):
            if self.bank[r] > 0:
                self.hands[p].add(r, 1)
                self.bank[r] -= 1

    def play_road_building(self, p: int, edges: list[int]) -> None:
        self._consume(p, DevCard.ROAD_BUILDING)
        for e in edges[:2]:
            self.build_road(p, e, free=True)

    def _rob(self, p: int) -> None:
        best = None
        for t in self.board.tiles.values():
            if t.resource is None or t.index == self.robber or self.adjacent(p, t.index):
                continue
            victims = {self.corners[c][0] for c in self.board.tile_corners[t.index] if c in self.corners}
            victims.discard(p)
            if not victims:
                continue
            weight = 0
            for c in self.board.tile_corners[t.index]:
                o = self.corners.get(c)
                if o and o[0] != p:
                    weight += (2 if o[1] == "city" else 1) * (1 + self.vp(o[0]) / 5)
            score = (weight * t.pips, t.pips)
            if best is None or score > best[0]:
                best = (score, t.index, victims)
        if best is None:
            return
        _, tile, victims = best
        self.robber = tile
        with_cards = [v for v in victims if self.hands[v].total() > 0]
        if not with_cards:
            return
        victim = max(with_cards, key=lambda v: (self.vp(v), self.hands[v].total()))
        pool = self.hands[victim].as_list()
        card = pool[int(self.rng.random() * len(pool))]
        self.hands[victim].add(card, -1)
        self.hands[p].add(card, 1)

    def play_knight(self, p: int) -> None:
        self._consume(p, DevCard.KNIGHT)
        self.knights[p] += 1
        self._rob(p)
        self._update_largest_army(p)

    def _produce(self, total: int) -> None:
        demand: dict[Resource, Counter] = {r: Counter() for r in RESOURCES}
        for t in self.board.tiles.values():
            if t.number != total or t.resource is None or t.index == self.robber:
                continue
            for c in self.board.tile_corners[t.index]:
                o = self.corners.get(c)
                if o:
                    demand[t.resource][o[0]] += 2 if o[1] == "city" else 1
        for r, per in demand.items():
            need = sum(per.values())
            if not need:
                continue
            if need > self.bank[r]:
                if len(per) != 1:
                    continue
                (only, _), = per.items()
                per = Counter({only: self.bank[r]})
            for q, n in per.items():
                self.hands[q].add(r, n)
                self.bank[r] -= n
                if q == self.hero:
                    self.hero_produced.add(r, n)

    def _seven(self, roller: int, discard: Callable[[int, int], Cards]) -> None:
        for q in self.order:
            n = self.hands[q].total()
            if n > DISCARD_LIMIT:
                cards = discard(q, n // 2)
                self.hands[q] -= cards
                for r in RESOURCES:
                    self.bank[r] += cards[r]
        self._rob(roller)

    def run(self, max_turns: int) -> FullResult:
        def discard(q: int, n: int) -> Cards:
            return self.policies[q].discard(PlayerView(self, q), n)

        for _ in range(max_turns):
            p = self.order[self.idx]
            if self.turn in self.dice:
                total = self.dice[self.turn]
            else:
                total = self.dice_rng.randint(1, 6) + self.dice_rng.randint(1, 6)
            if total == 7:
                self._seven(p, discard)
            else:
                self._produce(total)
            self.policies[p].take_turn(PlayerView(self, p))
            if self.vp(p) >= VICTORY_POINTS_TO_WIN:
                self.note(f"{self.name(p)} reaches {self.vp(p)} VP")
                return FullResult(p, self.turn, {q: self.vp(q) for q in self.order}, self.log)
            self.idx = (self.idx + 1) % len(self.order)
            self.turn += 1
        return FullResult(None, self.turn, {q: self.vp(q) for q in self.order}, self.log)


class PlayerView:
    def __init__(self, game: FullGame, player: int):
        self.g = game
        self.p = player

    @property
    def turn(self) -> int:
        return self.g.turn

    @property
    def hand(self) -> Cards:
        return self.g.hands[self.p].copy()

    @property
    def vp(self) -> int:
        return self.g.vp(self.p)

    @property
    def board(self):
        return self.g.board

    def ratios(self):
        return self.g.ratios(self.p)

    def bank(self):
        return dict(self.g.bank)

    def hero_corners(self):
        return self.g.owned(self.p)

    def opponents_holding(self, r: Resource) -> int:
        return sum(self.g.hands[q][r] for q in self.g.order if q != self.p)

    def robber_blocks_hero(self) -> bool:
        return self.g.adjacent(self.p, self.g.robber)

    def dev_cards(self):
        return [c for c, _ in self.g.devs[self.p]]

    def playable(self, card: DevCard) -> bool:
        return self.g.playable(self.p, card)

    def deck_remaining(self) -> int:
        return len(self.g.stack)

    def plan(self, need: Cards, keep=None):
        return self.g.plan(self.p, need, keep)

    def pieces_left(self, kind: str) -> int:
        return self.g.pieces_left(self.p, kind)

    def settlement_options(self, max_roads: int):
        return self.g.settlement_options(self.p, max_roads)

    def road_legal(self, edge: int) -> bool:
        return self.g.road_legal(self.p, edge)

    def build_city(self, corner: int, keep=None) -> bool:
        return self.g.build_city(self.p, corner, keep)

    def build_settlement(self, corner: int, path=None, keep=None) -> bool:
        return self.g.build_settlement(self.p, corner, path, keep)

    def build_road(self, edge: int, keep=None) -> bool:
        return self.g.build_road(self.p, edge, keep=keep)

    def buy_dev(self, keep=None) -> bool:
        return self.g.buy_dev(self.p, keep)

    def trade(self, t: Trade) -> None:
        self.g.trade(self.p, t)

    def play_monopoly(self, r: Resource) -> int:
        return self.g.play_monopoly(self.p, r)

    def play_year_of_plenty(self, a: Resource, b: Resource) -> None:
        self.g.play_year_of_plenty(self.p, a, b)

    def play_road_building(self, edges: list[int]) -> None:
        self.g.play_road_building(self.p, edges)

    def play_knight(self) -> None:
        self.g.play_knight(self.p)
