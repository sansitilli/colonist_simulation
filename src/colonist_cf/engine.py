from __future__ import annotations

import copy
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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
from .deck import Deck, full_order, recorded_draws
from .replay import (
    BankTrade,
    Build,
    DevBuy,
    DevPlay,
    Discard,
    Event,
    Monopoly,
    PlayerTrade,
    Produce,
    Replay,
    RobberMove,
    Roll,
    Steal,
    YearOfPlenty,
    vp_total,
    LARGEST_ARMY_KEY,
)
from .trading import Trade, plan_trades

if TYPE_CHECKING:
    from .policy import Policy


@dataclass
class Branch:
    name: str
    roads: list[tuple[int, int]] = field(default_factory=list)
    settlements: list[int] = field(default_factory=list)
    cities: list[int] = field(default_factory=list)


@dataclass
class Outcome:
    branch: str
    policy: str
    seed: int
    win_turn: int | None
    continued: bool
    final_vp: int
    horizon_turn: int
    vp_by_turn: dict[int, int]
    produced: Cards
    lost: Cards
    trades: list[tuple[int, Trade]]
    purchases: list[tuple[int, str]]
    log: list[str]
    issues: list[str]
    lost_to: int | None = None
    lost_turn: int | None = None
    winner: int | None = None
    winner_turn: int | None = None
    final_vps: dict[int, int] = field(default_factory=dict)

    @property
    def won_in_record(self) -> bool:
        return self.win_turn is not None and self.win_turn <= self.horizon_turn


def cost(kind: str) -> Cards:
    return Cards(COST[kind])


class Engine:
    def __init__(
        self,
        replay: Replay,
        hero: int,
        decision_event: int,
        branch: Branch,
        policy: "Policy",
        seed: int = 0,
        deck_mode: str = "queue",
        known_dev_order: list[int] | None = None,
        continue_turns: int = 0,
        opponent_policy: dict | None = None,
        verbose: bool = False,
    ):
        self.replay = replay
        self.board = replay.board
        self.hero = hero
        self.start = decision_event
        self.branch = branch
        self.policy = policy
        self.seed = seed
        self.continue_turns = continue_turns
        self.opponent_policy = opponent_policy or {"name": "adaptive"}
        self.continued = False
        self.final_vps: dict[int, int] = {}
        self.verbose = verbose
        self.order = replay.play_order
        self.opponents = [p for p in self.order if p != hero]

        self.rec: dict[int, Cards] = {p: Cards() for p in self.order}
        self.adj: dict[int, Cards] = {p: Cards() for p in self.order}
        self.hand = Cards()
        self.bank_rec: dict[Resource, int] = dict(replay.initial_bank)
        self.bank_adj = Cards()
        self.hero_corners: dict[int, str] = {}
        self.hero_roads: set[int] = set()
        self.opp_corners: dict[int, tuple[int, str]] = {}
        self.opp_roads: dict[int, int] = {}
        self.robber = replay.initial_robber
        self.robber_override: int | None = None
        self.dev_hand: list[list] = []
        self.vp_cards = 0
        self.knights = 0
        self.opp_knights: Counter = Counter()
        self.dev_played_turn: int | None = None
        self.rec_vp: dict[int, dict[int, int]] = {p: {} for p in self.order}
        self.opp_vp_adj: Counter = Counter()
        self.opp_devs: dict[int, Counter] = {p: Counter() for p in self.order}
        self.lost_to: int | None = None
        self.lost_turn: int | None = None

        self.turn = 0
        self.event_index = decision_event
        self.won_turn: int | None = None
        self.vp_by_turn: dict[int, int] = {}
        self.produced = Cards()
        self.lost = Cards()
        self.trades: list[tuple[int, Trade]] = []
        self.purchases: list[tuple[int, str]] = []
        self.log: list[str] = []
        self.issues: list[str] = []

        self._prepare()
        self.deck = Deck(
            order=full_order(replay, known_dev_order, random.Random(f"deck:{seed}")),
            hero=hero,
            start_event=decision_event,
            mode=deck_mode,
            draws=recorded_draws(replay),
        )

    def _prepare(self) -> None:
        for ev in self.replay.events[: self.start]:
            for a in ev.actions:
                if isinstance(a, Build):
                    self._place(a.player, a.piece, a.location)
                elif isinstance(a, RobberMove):
                    self.robber = a.tile
                elif isinstance(a, DevBuy) and a.player == self.hero:
                    self.dev_hand.append([a.card, ev.turn])
                    if a.card == DevCard.VICTORY_POINT:
                        self.vp_cards += 1
                elif isinstance(a, DevBuy) and a.player != self.hero and a.card is not None:
                    self.opp_devs[a.player][a.card] += 1
                elif isinstance(a, DevPlay):
                    if a.player != self.hero:
                        self.opp_devs[a.player][a.card] -= 1
                    if a.player == self.hero:
                        self._remove_dev(a.card)
                        if a.card == DevCard.KNIGHT:
                            self.knights += 1
                    elif a.card == DevCard.KNIGHT:
                        self.opp_knights[a.player] += 1
            self._apply_snapshot(ev)
        self.hand = self.rec[self.hero].copy()
        self.turn = self.replay.events[self.start].turn

    def _place(self, player: int, piece: str, location: int) -> None:
        if location < 0:
            return
        if piece == "road":
            if player == self.hero:
                self.hero_roads.add(location)
            else:
                self.opp_roads[location] = player
        elif player == self.hero:
            self.hero_corners[location] = piece
        else:
            self.opp_corners[location] = (player, piece)

    def _remove_dev(self, card: DevCard) -> None:
        for i, (c, _) in enumerate(self.dev_hand):
            if c == card:
                del self.dev_hand[i]
                return

    def _apply_snapshot(self, ev: Event) -> None:
        for p, cards in ev.hands.items():
            if p in self.rec:
                self.rec[p] = cards.copy()
        for r, n in ev.bank.items():
            self.bank_rec[r] = n
        if ev.robber is not None:
            self.robber = ev.robber
            self.robber_override = None
        for p, st in ev.vp_state.items():
            if p in self.rec_vp:
                self.rec_vp[p].update(st)

    def hero_has_largest_army(self) -> bool:
        return self.knights >= 3 and self.knights > max(self.opp_knights.values(), default=0)

    def opp_vp(self, p: int) -> int:
        pts = vp_total(self.rec_vp[p]) + self.opp_vp_adj[p]
        if self.hero_has_largest_army() and self.rec_vp[p].get(LARGEST_ARMY_KEY):
            pts -= 2
        return pts

    def opp_hand(self, p: int) -> Cards:
        return self.rec[p] + self.adj[p]

    def bank(self) -> dict[Resource, int]:
        return {r: self.bank_rec[r] + self.bank_adj[r] for r in RESOURCES}

    def ratios(self) -> dict[Resource, int]:
        return self.board.trade_ratios(set(self.hero_corners))

    def vp(self) -> int:
        pts = sum(2 if k == "city" else 1 for k in self.hero_corners.values())
        pts += self.vp_cards
        if self.hero_has_largest_army():
            pts += 2
        return pts

    def note(self, text: str) -> None:
        self.log.append(f"t{self.turn}: {text}")

    def issue(self, text: str) -> None:
        self.issues.append(f"e{self.event_index} t{self.turn}: {text}")

    def _pick(self, cards: Cards, salt: str) -> Resource | None:
        pool = cards.as_list()
        if not pool:
            return None
        u = random.Random(f"{self.seed}:{self.event_index}:{salt}").random()
        return pool[int(u * len(pool))]

    def effective_robber(self) -> int:
        return self.robber if self.robber_override is None else self.robber_override

    def hero_adjacent(self, tile: int) -> bool:
        return any(c in self.hero_corners for c in self.board.tile_corners.get(tile, []))

    def production(self, total: int) -> Cards:
        out = Cards()
        robber = self.effective_robber()
        for t in self.board.tiles.values():
            if t.number != total or t.resource is None or t.index == robber:
                continue
            for c in self.board.tile_corners[t.index]:
                kind = self.hero_corners.get(c)
                if kind:
                    out.add(t.resource, 2 if kind == "city" else 1)
        return out

    def occupied(self, corner: int) -> bool:
        return corner in self.hero_corners or corner in self.opp_corners

    def settlement_legal(self, corner: int, roads: set[int] | None = None) -> bool:
        if self.occupied(corner):
            return False
        if any(self.occupied(n) for n in self.board.corner_neighbors[corner]):
            return False
        network = self.hero_roads if roads is None else roads
        return any(e in network for e in self.board.corner_edges[corner])

    def road_legal(self, edge: int, roads: set[int] | None = None) -> bool:
        if edge in self.opp_roads or edge in self.hero_roads:
            return False
        network = self.hero_roads if roads is None else roads
        for c in self.board.edge_corners[edge]:
            if c in self.hero_corners:
                return True
            if c in self.opp_corners:
                continue
            if any(e in network for e in self.board.corner_edges[c]):
                return True
        return False

    def settlement_options(self, max_roads: int) -> list[tuple[int, list[int]]]:
        start: set[int] = set(self.hero_corners)
        for e in self.hero_roads:
            for c in self.board.edge_corners[e]:
                if c not in self.opp_corners:
                    start.add(c)
        best: dict[int, list[int]] = {c: [] for c in start}
        frontier = list(start)
        for _ in range(max_roads):
            nxt = []
            for c in frontier:
                for e in self.board.corner_edges[c]:
                    if e in self.opp_roads or e in self.hero_roads:
                        continue
                    a, b = self.board.edge_corners[e]
                    d = b if a == c else a
                    if d in best or d in self.opp_corners:
                        continue
                    best[d] = best[c] + [e]
                    nxt.append(d)
            frontier = nxt
        out = []
        for c, path in best.items():
            if self.settlement_legal(c, self.hero_roads | set(path)):
                out.append((c, path))
        return out

    def pieces_left(self, kind: str) -> int:
        if kind == "road":
            return PIECE_LIMIT["road"] - len(self.hero_roads)
        if kind == "settlement":
            return PIECE_LIMIT["settlement"] - sum(1 for k in self.hero_corners.values() if k == "settlement")
        if kind == "city":
            return PIECE_LIMIT["city"] - sum(1 for k in self.hero_corners.values() if k == "city")
        return 0

    def plan(self, need: Cards, keep: dict[Resource, float] | None = None) -> list[Trade] | None:
        return plan_trades(self.hand, need, self.ratios(), self.bank(), keep)

    def trade(self, t: Trade) -> None:
        if self.hand[t.give] < t.ratio or self.bank()[t.get] < 1:
            raise RuntimeError(f"illegal trade {t}")
        self.hand.add(t.give, -t.ratio)
        self.hand.add(t.get, 1)
        self.bank_adj.add(t.give, t.ratio)
        self.bank_adj.add(t.get, -1)
        self.trades.append((self.turn, t))
        self.note(f"trade {t.ratio}x{t.give.name.lower()} -> {t.get.name.lower()}")

    def pay(self, need: Cards, keep: dict[Resource, float] | None = None) -> bool:
        trades = self.plan(need, keep)
        if trades is None:
            return False
        for t in trades:
            self.trade(t)
        self.hand -= need
        self.bank_adj += need
        return True

    def build_road(self, edge: int, free: bool = False, keep=None) -> bool:
        if not self.road_legal(edge) or self.pieces_left("road") < 1:
            return False
        if not free and not self.pay(cost("road"), keep):
            return False
        self.hero_roads.add(edge)
        self.purchases.append((self.turn, f"road {self.board.edge_corners[edge]}"))
        self.note(f"road {self.board.edge_corners[edge]}{' (free)' if free else ''}")
        return True

    def build_settlement(self, corner: int, path: list[int] | None = None, keep=None) -> bool:
        path = path or []
        if self.pieces_left("settlement") < 1 or self.pieces_left("road") < len(path):
            return False
        if not self.settlement_legal(corner, self.hero_roads | set(path)):
            return False
        total = cost("settlement")
        for _ in path:
            total += cost("road")
        if not self.pay(total, keep):
            return False
        for e in path:
            self.hero_roads.add(e)
            self.purchases.append((self.turn, f"road {self.board.edge_corners[e]}"))
        self.hero_corners[corner] = "settlement"
        self.purchases.append((self.turn, f"settlement {corner}"))
        self.note(f"settlement {corner} [{self.board.corner_label(corner)}]")
        return True

    def build_city(self, corner: int, keep=None) -> bool:
        if self.hero_corners.get(corner) != "settlement" or self.pieces_left("city") < 1:
            return False
        if not self.pay(cost("city"), keep):
            return False
        self.hero_corners[corner] = "city"
        self.purchases.append((self.turn, f"city {corner}"))
        self.note(f"city {corner}")
        return True

    def buy_dev(self, keep=None) -> bool:
        if self.deck.remaining() <= 0:
            return False
        if not self.pay(cost("dev"), keep):
            return False
        card = self.deck.draw_hero()
        if card is None:
            self.issue("deck exhausted after payment")
            return False
        self.dev_hand.append([card, self.turn])
        if card == DevCard.VICTORY_POINT:
            self.vp_cards += 1
        self.purchases.append((self.turn, f"dev {card.name.lower()}"))
        self.note(f"bought {card.name.lower()}")
        return True

    def playable(self, card: DevCard) -> bool:
        if self.dev_played_turn == self.turn:
            return False
        return any(c == card and t < self.turn for c, t in self.dev_hand)

    def _consume(self, card: DevCard) -> None:
        for i, (c, t) in enumerate(self.dev_hand):
            if c == card and t < self.turn:
                del self.dev_hand[i]
                self.dev_played_turn = self.turn
                return
        raise RuntimeError(f"{card} not playable")

    def play_monopoly(self, r: Resource) -> int:
        self._consume(DevCard.MONOPOLY)
        got = 0
        for p in self.opponents:
            n = max(0, self.opp_hand(p)[r])
            if n:
                self.adj[p].add(r, -n)
                got += n
        self.hand.add(r, got)
        self.note(f"monopoly {r.name.lower()} +{got}")
        return got

    def play_year_of_plenty(self, a: Resource, b: Resource) -> None:
        bank = self.bank()
        if bank[a] < 1 or bank[b] < (2 if a == b else 1):
            raise RuntimeError("bank cannot pay year of plenty")
        self._consume(DevCard.YEAR_OF_PLENTY)
        for r in (a, b):
            self.hand.add(r, 1)
            self.bank_adj.add(r, -1)
        self.note(f"year of plenty {a.name.lower()}+{b.name.lower()}")

    def play_road_building(self, edges: list[int]) -> None:
        self._consume(DevCard.ROAD_BUILDING)
        for e in edges[:2]:
            self.build_road(e, free=True)

    def play_knight(self) -> None:
        self._consume(DevCard.KNIGHT)
        self.knights += 1
        best = None
        for t in self.board.tiles.values():
            if t.resource is None or t.index == self.effective_robber() or self.hero_adjacent(t.index):
                continue
            victims = {self.opp_corners[c][0] for c in self.board.tile_corners[t.index] if c in self.opp_corners}
            victims = [v for v in victims if self.opp_hand(v).total() > 0]
            score = (t.pips * len(victims), t.pips)
            if victims and (best is None or score > best[0]):
                best = (score, t.index, max(victims, key=lambda v: self.opp_hand(v).total()))
        if best is None:
            self.note("knight played, no target")
            return
        _, tile, victim = best
        self.robber_override = tile
        card = self._pick(self.opp_hand(victim).clamp(), "knight")
        if card is not None:
            self.adj[victim].add(card, -1)
            self.hand.add(card, 1)
        self.issue("hero knight moves the robber off the recorded tile; opponents' production is not re-simulated")
        self.note(f"knight robber->{self.board.tiles[tile].label()} stole {card.name.lower() if card else 'nothing'} from {self.replay.name(victim)}")

    def discard(self, n: int) -> None:
        self.discard_due = n
        self.apply_discard(self.policy.discard(HeroView(self), n))

    def _apply_branch(self) -> None:
        for a, b in self.branch.roads:
            e = self.board.edge_between(a, b)
            if e is None:
                raise ValueError(f"branch {self.branch.name}: no edge between {a} and {b}")
            if not self.build_road(e):
                raise ValueError(f"branch {self.branch.name}: road {a}-{b} illegal or unaffordable, hand {self.hand}")
        for c in self.branch.settlements:
            if not self.build_settlement(c):
                raise ValueError(f"branch {self.branch.name}: settlement {c} illegal or unaffordable, hand {self.hand}")
        for c in self.branch.cities:
            if not self.build_city(c):
                raise ValueError(f"branch {self.branch.name}: city {c} illegal or unaffordable, hand {self.hand}")

    def _handle(self, ev: Event, a, before: dict[int, Cards]) -> None:
        h = self.hero
        if isinstance(a, Roll):
            if a.total == 7:
                return
            prod = self.production(a.total)
            others = Cards()
            for b in ev.actions:
                if isinstance(b, Produce) and b.player != h:
                    others += b.cards
            bank = self.bank()
            for r in RESOURCES:
                if prod[r] and bank[r] < prod[r] + others[r]:
                    self.issue(f"bank short of {r.name.lower()}, hero production reduced")
                    prod[r] = max(0, min(prod[r], bank[r] - others[r]))
            self.hand += prod
            self.bank_adj -= prod
            self.produced += prod
            if prod.total():
                self.note(f"roll {a.total}: +{prod}")
        elif isinstance(a, Produce):
            if a.player == h:
                self.bank_adj += a.cards
        elif isinstance(a, Discard):
            if a.player == h:
                self.bank_adj -= a.cards
        elif isinstance(a, RobberMove):
            self.robber = a.tile
            self.robber_override = None
            if a.player != h and a.victim is None and self.hero_adjacent(a.tile) and self.hand.total():
                card = self._pick(self.hand, "robber")
                self.hand.add(card, -1)
                self.adj[a.player].add(card, 1)
                self.lost.add(card)
                self.note(f"{self.replay.name(a.player)} robbed {card.name.lower()} (no recorded victim)")
            if a.player == h and a.cause == "knight":
                self.issue("recorded hero knight dropped; its robber tile is kept")
        elif isinstance(a, Steal):
            self._steal(a, before)
        elif isinstance(a, DevBuy):
            if a.player == h:
                self.bank_adj -= cost("dev")
            else:
                card = self.deck.draw_opponent(a.card)
                if card is not None:
                    self.opp_devs[a.player][card] += 1
                if card != a.card:
                    if card == DevCard.VICTORY_POINT:
                        self.opp_vp_adj[a.player] += 1
                    if a.card == DevCard.VICTORY_POINT:
                        self.opp_vp_adj[a.player] -= 1
                    name = card.name.lower() if card else "nothing"
                    self.note(f"{self.replay.name(a.player)} draws {name} instead of {a.card.name.lower()}")
                    self.issue(f"{self.replay.name(a.player)} dev draw changed by deck position")
        elif isinstance(a, DevPlay):
            if a.player != h:
                if self.opp_devs[a.player][a.card] <= 0:
                    self.issue(f"{self.replay.name(a.player)} plays {a.card.name.lower()} not held after deck shift")
                self.opp_devs[a.player][a.card] -= 1
                if a.card == DevCard.KNIGHT:
                    self.opp_knights[a.player] += 1
        elif isinstance(a, Monopoly):
            if a.player == h:
                for p in self.opponents:
                    after = ev.hands.get(p)
                    if after is not None:
                        self.adj[p].add(a.resource, before[p][a.resource] - after[a.resource])
            else:
                r = a.resource
                delta = 0
                for p in self.order:
                    if p == a.player:
                        continue
                    if p == h:
                        k = self.hand[r]
                        self.hand[r] = 0
                        self.lost.add(r, k)
                        delta += k - before[h][r]
                        if k:
                            self.note(f"{self.replay.name(a.player)} monopoly took {k} {r.name.lower()}")
                    else:
                        k = max(0, before[p][r] + self.adj[p][r])
                        delta += k - before[p][r]
                        self.adj[p][r] = 0
                self.adj[a.player].add(r, delta)
        elif isinstance(a, YearOfPlenty):
            if a.player == h:
                self.bank_adj += a.cards
        elif isinstance(a, Build):
            if a.player == h:
                if not a.free:
                    self.bank_adj -= cost(a.piece)
                return
            if a.piece != "road" and a.location >= 0:
                if a.location in self.hero_corners:
                    self.issue(f"{self.replay.name(a.player)} recorded build on hero corner {a.location}")
                elif a.piece == "settlement" and any(
                    n in self.hero_corners for n in self.board.corner_neighbors[a.location]
                ):
                    self.issue(f"{self.replay.name(a.player)} recorded settlement {a.location} next to a hero building")
            if a.piece == "road" and a.location in self.hero_roads:
                self.issue(f"{self.replay.name(a.player)} recorded road on hero edge {a.location}")
            self._place(a.player, a.piece, a.location)
        elif isinstance(a, BankTrade):
            if a.player == h:
                self.bank_adj -= a.given
                self.bank_adj += a.received
        elif isinstance(a, PlayerTrade):
            if a.player == h:
                self.adj[a.partner] += a.received - a.given
            elif a.partner == h:
                self.adj[a.player] += a.given - a.received

    def _steal(self, a: Steal, before: dict[int, Cards]) -> None:
        h = self.hero
        rec = Cards.of([a.card]) if a.card is not None else Cards()
        if a.victim == h and a.thief != h:
            if not self.hand.total():
                self.adj[a.thief] -= rec
                return
            card = self._pick(self.hand, "steal")
            self.hand.add(card, -1)
            self.adj[a.thief] += Cards.of([card]) - rec
            self.lost.add(card)
            self.note(f"{self.replay.name(a.thief)} stole {card.name.lower()}")
        elif a.thief == h:
            if a.cause == "knight":
                self.adj[a.victim] += rec
                return
            victim_hand = (before[a.victim] + self.adj[a.victim]).clamp()
            if a.card is not None and victim_hand[a.card] > 0:
                self.hand.add(a.card, 1)
                card = a.card
            else:
                card = self._pick(victim_hand, "rob")
                self.adj[a.victim] += rec
                if card is not None:
                    self.adj[a.victim].add(card, -1)
                    self.hand.add(card, 1)
            self.note(f"stole {card.name.lower() if card else 'nothing'} from {self.replay.name(a.victim)}")

    def end_turn(self) -> None:
        self.vp_by_turn[self.turn] = self.vp()
        devs = ",".join(c.name.lower() for c, _ in self.dev_hand) or "-"
        self.note(f"end of turn: {self.vp()} VP, hand {self.hand}, dev [{devs}]")
        if self.vp() >= VICTORY_POINTS_TO_WIN and self.won_turn is None:
            self.won_turn = self.turn
            self.note(f"reaches {self.vp()} VP")

    def _hero_turn(self) -> None:
        self.policy.take_turn(HeroView(self))
        self.end_turn()

    def _check_opponents(self, ev: Event) -> None:
        for p in ev.hands:
            if p != self.hero and p in self.adj and not self.opp_hand(p).is_valid():
                self.issue(f"{self.replay.name(p)} counterfactual hand negative {self.opp_hand(p).v}")
                self.adj[p] = self.adj[p] - (self.opp_hand(p) - self.opp_hand(p).clamp())

    def begin(self) -> None:
        self.policy.begin(HeroView(self))
        self._apply_branch()
        self._cursor = self.start
        self._final_done = False
        self._pending = None
        self.discard_due = 0

    def advance(self) -> str:
        events = self.replay.events
        while True:
            if self._pending is None:
                if self._cursor >= len(events):
                    break
                ev = events[self._cursor]
                self._cursor += 1
                self.event_index = ev.index
                self.turn = ev.turn
                before = {p: c.copy() for p, c in self.rec.items()}
                idx = 0
            else:
                ev, idx, before = self._pending
                self._pending = None
            while idx < len(ev.actions):
                a = ev.actions[idx]
                idx += 1
                if isinstance(a, Roll) and a.total == 7 and self.hand.total() > DISCARD_LIMIT:
                    self._pending = (ev, idx, before)
                    self.discard_due = self.hand.total() // 2
                    return "discard"
                self._handle(ev, a, before)
            self._apply_snapshot(ev)
            self._check_opponents(ev)
            if ev.ends_turn and ev.player in self.opponents and self.won_turn is None:
                if self.opp_vp(ev.player) >= VICTORY_POINTS_TO_WIN:
                    self.lost_to = ev.player
                    self.lost_turn = ev.turn
                    self.note(f"{self.replay.name(ev.player)} reaches {self.opp_vp(ev.player)} VP and wins")
                    return "lost"
            if ev.player == self.hero and ev.ends_turn:
                return "turn"
        last = events[-1]
        if not self._final_done and last.player == self.hero and not last.ends_turn:
            self._final_done = True
            self.turn = last.turn
            return "turn"
        return ""

    def apply_discard(self, cards: Cards) -> None:
        if cards.total() != self.discard_due or not self.hand.covers(cards):
            raise RuntimeError(f"invalid discard {cards} of {self.discard_due} from {self.hand}")
        self.hand -= cards
        self.bank_adj += cards
        self.lost += cards
        self.discard_due = 0
        self.note(f"discarded {cards}")

    @property
    def record_horizon(self) -> int:
        return self.replay.events[-1].turn

    def clone(self) -> "Engine":
        memo = {id(self.replay): self.replay, id(self.board): self.board}
        return copy.deepcopy(self, memo)

    def outcome(self) -> Outcome:
        if not self.final_vps:
            self.final_vps = {p: self.opp_vp(p) for p in self.opponents} | {self.hero: self.vp()}
        winner = self.hero if self.won_turn is not None else self.lost_to
        return Outcome(
            branch=self.branch.name,
            policy=self.policy.name,
            seed=self.seed,
            win_turn=self.won_turn,
            continued=self.continued,
            final_vp=self.final_vps.get(self.hero, self.vp()),
            horizon_turn=self.record_horizon,
            vp_by_turn=self.vp_by_turn,
            produced=self.produced,
            lost=self.lost,
            trades=self.trades,
            purchases=self.purchases,
            log=self.log,
            issues=self.issues,
            lost_to=self.lost_to,
            lost_turn=self.lost_turn,
            winner=winner,
            winner_turn=self.won_turn if winner == self.hero else self.lost_turn,
            final_vps=dict(self.final_vps),
        )

    def run(self) -> Outcome:
        self.begin()
        while self.won_turn is None:
            status = self.advance()
            if status == "turn":
                self._hero_turn()
            elif status == "discard":
                self.apply_discard(self.policy.discard(HeroView(self), self.discard_due))
            else:
                break
        if self.won_turn is None and self.lost_to is None and self.continue_turns > 0:
            last = self.replay.events[-1]
            nxt = self.order[(self.order.index(last.player) + 1) % len(self.order)]
            self._full_game(last.turn + 1, nxt)
        return self.outcome()

    def _full_game(self, start_turn: int, first: int, dice: dict[int, int] | None = None) -> None:
        from .fullgame import FullGame
        from .policy import make_opponent_policy

        policies = {p: make_opponent_policy(self.opponent_policy) for p in self.opponents}
        policies[self.hero] = self.policy
        game = FullGame(self, policies, self.seed, start_turn, first, dice)
        res = game.run(self.continue_turns)
        self.log.extend(game.log)
        self.trades.extend(game.hero_trades)
        self.produced += game.hero_produced
        self.continued = True
        self.final_vps = res.vp
        if res.winner == self.hero:
            self.won_turn = res.turn
        elif res.winner is not None:
            self.lost_to = res.winner
            self.lost_turn = res.turn

    def run_from_decision(self, recorded_dice: bool = True) -> Outcome:
        self.begin()
        nxt = self.order[(self.order.index(self.hero) + 1) % len(self.order)]
        dice = self.replay.recorded_rolls() if recorded_dice else None
        self._full_game(self.turn + 1, nxt, dice)
        return self.outcome()


class HeroView:
    def __init__(self, engine: Engine):
        self.e = engine

    @property
    def turn(self) -> int:
        return self.e.turn

    @property
    def hand(self) -> Cards:
        return self.e.hand.copy()

    @property
    def vp(self) -> int:
        return self.e.vp()

    @property
    def board(self):
        return self.e.board

    def ratios(self) -> dict[Resource, int]:
        return self.e.ratios()

    def bank(self) -> dict[Resource, int]:
        return self.e.bank()

    def hero_corners(self) -> dict[int, str]:
        return dict(self.e.hero_corners)

    def opponents_holding(self, r: Resource) -> int:
        return sum(max(0, self.e.opp_hand(p)[r]) for p in self.e.opponents)

    def robber_blocks_hero(self) -> bool:
        return self.e.hero_adjacent(self.e.effective_robber())

    def dev_cards(self) -> list[DevCard]:
        return [c for c, _ in self.e.dev_hand]

    def playable(self, card: DevCard) -> bool:
        return self.e.playable(card)

    def deck_remaining(self) -> int:
        return self.e.deck.remaining()

    def plan(self, need: Cards, keep=None):
        return self.e.plan(need, keep)

    def pieces_left(self, kind: str) -> int:
        return self.e.pieces_left(kind)

    def settlement_options(self, max_roads: int):
        return self.e.settlement_options(max_roads)

    def road_legal(self, edge: int) -> bool:
        return self.e.road_legal(edge)

    def build_city(self, corner: int, keep=None) -> bool:
        return self.e.build_city(corner, keep)

    def build_settlement(self, corner: int, path=None, keep=None) -> bool:
        return self.e.build_settlement(corner, path, keep)

    def build_road(self, edge: int, keep=None) -> bool:
        return self.e.build_road(edge, keep=keep)

    def buy_dev(self, keep=None) -> bool:
        return self.e.buy_dev(keep)

    def trade(self, t: Trade) -> None:
        self.e.trade(t)

    def play_monopoly(self, r: Resource) -> int:
        return self.e.play_monopoly(r)

    def play_year_of_plenty(self, a: Resource, b: Resource) -> None:
        self.e.play_year_of_plenty(a, b)

    def play_road_building(self, edges: list[int]) -> None:
        self.e.play_road_building(edges)

    def play_knight(self) -> None:
        self.e.play_knight()
