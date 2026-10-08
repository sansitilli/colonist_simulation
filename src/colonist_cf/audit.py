from __future__ import annotations

from dataclasses import dataclass, field

from .cards import Cards
from .constants import COST
from .replay import (
    BankTrade,
    Build,
    DevBuy,
    Discard,
    Grant,
    Monopoly,
    PlayerTrade,
    Produce,
    Replay,
    RobberMove,
    Roll,
    Steal,
    YearOfPlenty,
)


@dataclass
class AuditReport:
    player: int
    snapshots: int = 0
    rolls: int = 0
    dev_checked: int = 0
    hand_mismatches: list[str] = field(default_factory=list)
    production_mismatches: list[str] = field(default_factory=list)
    dev_mismatches: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.hand_mismatches or self.production_mismatches or self.dev_mismatches)


def _expected_production(replay: Replay, corners: dict[int, str], robber: int, total: int) -> Cards:
    out = Cards()
    for t in replay.board.tiles.values():
        if t.number != total or t.resource is None or t.index == robber:
            continue
        for c in replay.board.tile_corners[t.index]:
            if c in corners:
                out.add(t.resource, 2 if corners[c] == "city" else 1)
    return out


def audit(replay: Replay, player: int) -> AuditReport:
    rep = AuditReport(player)
    hand = Cards()
    corners: dict[int, str] = {}
    robber = replay.initial_robber
    for ev in replay.events:
        bought = []
        for a in ev.actions:
            if isinstance(a, Roll):
                if a.total != 7:
                    rep.rolls += 1
                    expect = _expected_production(replay, corners, robber, a.total)
                    got = Cards()
                    for b in ev.actions:
                        if isinstance(b, Produce) and b.player == player:
                            got += b.cards
                    if got != expect:
                        rep.production_mismatches.append(
                            f"event {ev.index} roll {a.total}: computed {expect}, recorded {got}"
                        )
            elif isinstance(a, (Produce, Grant, YearOfPlenty)) and a.player == player:
                hand += a.cards
            elif isinstance(a, Discard) and a.player == player:
                hand -= a.cards
            elif isinstance(a, RobberMove):
                robber = a.tile
            elif isinstance(a, Steal):
                c = Cards.of([a.card]) if a.card is not None else Cards()
                if a.thief == player:
                    hand += c
                if a.victim == player:
                    hand -= c
            elif isinstance(a, DevBuy) and a.player == player:
                hand -= Cards(COST["dev"])
                bought.append(a.card)
            elif isinstance(a, Monopoly):
                if a.player == player:
                    hand.add(a.resource, a.amount)
                else:
                    hand[a.resource] = 0
            elif isinstance(a, Build) and a.player == player:
                if not a.free:
                    hand -= Cards(COST[a.piece])
                if a.piece != "road":
                    corners[a.location] = a.piece
            elif isinstance(a, BankTrade) and a.player == player:
                hand -= a.given
                hand += a.received
            elif isinstance(a, PlayerTrade):
                if a.player == player:
                    hand -= a.given
                    hand += a.received
                elif a.partner == player:
                    hand += a.given
                    hand -= a.received
        if ev.robber is not None:
            robber = ev.robber
        if player in ev.hands:
            rep.snapshots += 1
            if ev.hands[player] != hand:
                rep.hand_mismatches.append(f"event {ev.index} t{ev.turn}: computed {hand}, recorded {ev.hands[player]}")
                hand = ev.hands[player].copy()
        visible = ev.dev_bought.get(player)
        if bought and visible:
            rep.dev_checked += len(bought)
            if visible[-len(bought):] != bought:
                rep.dev_mismatches.append(f"event {ev.index}: draw order says {bought}, replay shows {visible}")
    return rep
