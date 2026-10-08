from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from .board import Board
from .cards import Cards
from .constants import (
    ROLL_DISTRIBUTION,
    DevCard,
    Log,
    Piece,
    Resource,
)


@dataclass
class Roll:
    player: int
    total: int


@dataclass
class Produce:
    player: int
    cards: Cards


@dataclass
class Grant:
    player: int
    cards: Cards


@dataclass
class Discard:
    player: int
    cards: Cards


@dataclass
class RobberMove:
    player: int
    tile: int
    cause: str = "seven"
    victim: int | None = None
    card: Resource | None = None


@dataclass
class Steal:
    thief: int
    victim: int
    card: Resource | None
    cause: str = "seven"


@dataclass
class DevBuy:
    player: int
    card: DevCard | None
    draw_index: int


@dataclass
class DevPlay:
    player: int
    card: DevCard


@dataclass
class Monopoly:
    player: int
    resource: Resource
    amount: int


@dataclass
class YearOfPlenty:
    player: int
    cards: Cards


@dataclass
class Build:
    player: int
    piece: str
    location: int
    free: bool


@dataclass
class BankTrade:
    player: int
    given: Cards
    received: Cards


@dataclass
class PlayerTrade:
    player: int
    partner: int
    given: Cards
    received: Cards


Action = Union[
    Roll, Produce, Grant, Discard, RobberMove, Steal, DevBuy, DevPlay,
    Monopoly, YearOfPlenty, Build, BankTrade, PlayerTrade,
]


@dataclass
class Event:
    index: int
    turn: int
    player: int | None
    next_turn: int
    next_player: int | None
    actions: list[Action] = field(default_factory=list)
    hands: dict[int, Cards] = field(default_factory=dict)
    robber: int | None = None
    bank: dict[Resource, int] = field(default_factory=dict)
    dev_bought: dict[int, list[DevCard]] = field(default_factory=dict)
    vp_state: dict[int, dict[int, int]] = field(default_factory=dict)

    @property
    def ends_turn(self) -> bool:
        return self.next_player != self.player or self.next_turn != self.turn


@dataclass
class Player:
    color: int
    name: str


@dataclass
class Replay:
    game_id: str
    board: Board
    players: dict[int, Player]
    play_order: list[int]
    perspective: int | None
    initial_robber: int
    initial_bank: dict[Resource, int]
    events: list[Event]
    dev_draw_order: list[DevCard]
    total_turns: int
    winner: int | None

    def recorded_rolls(self) -> dict[int, int]:
        out: dict[int, int] = {}
        for ev in self.events:
            for a in ev.actions:
                if isinstance(a, Roll):
                    out.setdefault(ev.turn, a.total)
        return out

    def name(self, color: int) -> str:
        p = self.players.get(color)
        return p.name if p else str(color)

    def color_of(self, name_or_color: str | int) -> int:
        if isinstance(name_or_color, int) or str(name_or_color).isdigit():
            return int(name_or_color)
        for p in self.players.values():
            if p.name.lower() == str(name_or_color).lower():
                return p.color
        raise KeyError(f"unknown player {name_or_color}")


VP_WEIGHTS = {0: 1, 1: 2, 2: 1, 3: 2, 4: 2}
VP_CARD_KEY = 2
LARGEST_ARMY_KEY = 3


def vp_total(state: dict[int, int]) -> int:
    return sum(VP_WEIGHTS.get(k, 0) * n for k, n in state.items())


def _cards(values) -> Cards:
    return Cards.of(int(x) for x in values if 1 <= int(x) <= 5)


def load(path: str | Path) -> Replay:
    raw = json.loads(Path(path).read_text())
    return parse(raw.get("data", raw))


def parse(data: dict) -> Replay:
    history = data["eventHistory"]
    initial = history["initialState"]
    board = Board.from_map_state(initial["mapState"])
    players = {
        int(u["selectedColor"]): Player(int(u["selectedColor"]), u["username"])
        for u in data.get("playerUserStates", [])
    }
    end = history.get("endGameState", {}) or {}
    draw_order = [DevCard(c) for c in end.get("developmentCardStats", []) if c in DevCard._value2member_map_]
    winner = None
    for k, v in (end.get("players") or {}).items():
        if v.get("winningPlayer"):
            winner = int(k)

    state = initial["currentState"]
    turn = int(state.get("completedTurns", 0))
    current = state.get("currentTurnPlayerColor")
    corner_owner: dict[int, int] = {}
    events: list[Event] = []
    draws = 0
    pending: list[str] = []

    for i, e in enumerate(history["events"]):
        sc = e.get("stateChange", {})
        cs = sc.get("currentState", {}) or {}
        next_turn = int(cs.get("completedTurns", turn))
        next_player = cs.get("currentTurnPlayerColor", current)
        ev = Event(index=i, turn=turn, player=current, next_turn=next_turn, next_player=next_player)

        ms = sc.get("mapState", {}) or {}
        new_corners: list[tuple[int, str, int]] = []
        for k, v in (ms.get("tileCornerStates") or {}).items():
            if not v:
                continue
            c = int(k)
            if "owner" in v:
                corner_owner[c] = int(v["owner"])
            kind = "city" if v.get("buildingType") == 2 else "settlement"
            new_corners.append((c, kind, corner_owner.get(c, -1)))
        new_edges: list[tuple[int, int]] = []
        for k, v in (ms.get("tileEdgeStates") or {}).items():
            if v and "owner" in v:
                new_edges.append((int(k), int(v["owner"])))

        logs = sc.get("gameLogState", {}) or {}
        entries = sorted(((int(k), g) for k, g in logs.items() if g and "text" in g), key=lambda x: x[0])
        steal_cards: dict[tuple[int, int], Resource | None] = {}
        for _, g in entries:
            t = g["text"]
            if t.get("type") == Log.STOLE_VICTIM_VIEW and t.get("cardEnums"):
                steal_cards[("victim", int(t["playerColor"]))] = Resource(t["cardEnums"][0])
            if t.get("type") == Log.STOLE_THIEF_VIEW and t.get("cardEnums"):
                steal_cards[("thief", int(t["playerColor"]))] = Resource(t["cardEnums"][0])

        for _, g in entries:
            t = g["text"]
            ty = t.get("type")
            pc = t.get("playerColor")
            if ty == Log.ROLL:
                total = int(t["firstDice"]) + int(t["secondDice"])
                ev.actions.append(Roll(int(pc), total))
                if total == 7:
                    pending.append("seven")
            elif ty == Log.GOT_RESOURCES:
                cards = _cards(t.get("cardsToBroadcast", []))
                if t.get("distributionType") == ROLL_DISTRIBUTION:
                    ev.actions.append(Produce(int(pc), cards))
                else:
                    ev.actions.append(Grant(int(pc), cards))
            elif ty == Log.DISCARDED and t.get("areResourceCards", True):
                ev.actions.append(Discard(int(pc), _cards(t.get("cardEnums", []))))
            elif ty == Log.ROBBER_MOVED:
                tile = sc.get("mechanicRobberState", {}).get("locationTileIndex")
                cause = pending.pop() if pending else "seven"
                ev.actions.append(RobberMove(int(pc), int(tile) if tile is not None else -1, cause))
            elif ty == Log.STOLE_PUBLIC:
                thief, victim = int(t["playerColorThief"]), int(t["playerColorVictim"])
                card = steal_cards.get(("victim", victim)) or steal_cards.get(("thief", thief))
                ev.actions.append(Steal(thief, victim, card))
            elif ty == Log.DEV_BOUGHT:
                card = draw_order[draws] if draws < len(draw_order) else None
                ev.actions.append(DevBuy(int(pc), card, draws))
                draws += 1
            elif ty == Log.DEV_PLAYED:
                card = DevCard(int(t["cardEnum"]))
                ev.actions.append(DevPlay(int(pc), card))
                if card == DevCard.KNIGHT:
                    pending.append("knight")
            elif ty == Log.MONOPOLY:
                ev.actions.append(Monopoly(int(pc), Resource(int(t["cardEnum"])), int(t.get("amountStolen", 0))))
            elif ty == Log.YEAR_OF_PLENTY and t.get("cardEnums"):
                ev.actions.append(YearOfPlenty(int(pc), _cards(t["cardEnums"])))
            elif ty in (Log.BUILT, Log.PLACED_FREE):
                piece = Piece(int(t["pieceEnum"]))
                free = ty == Log.PLACED_FREE
                if piece == Piece.ROAD:
                    loc = next((e2 for e2, o in new_edges if o == pc), None)
                    if loc is not None:
                        new_edges.remove((loc, pc))
                    ev.actions.append(Build(int(pc), "road", -1 if loc is None else loc, free))
                else:
                    kind = "city" if piece == Piece.CITY else "settlement"
                    loc = next((c for c, k2, o in new_corners if k2 == kind and o == pc), None)
                    if loc is not None:
                        new_corners = [x for x in new_corners if x[0] != loc]
                    ev.actions.append(Build(int(pc), kind, -1 if loc is None else loc, free))
            elif ty == Log.BANK_TRADE:
                ev.actions.append(BankTrade(int(pc), _cards(t["givenCardEnums"]), _cards(t["receivedCardEnums"])))
            elif ty == Log.PLAYER_TRADE:
                ev.actions.append(
                    PlayerTrade(
                        int(pc),
                        int(t["acceptingPlayerColor"]),
                        _cards(t["givenCardEnums"]),
                        _cards(t["receivedCardEnums"]),
                    )
                )

        for p, v in (sc.get("playerStates") or {}).items():
            if v and "resourceCards" in v:
                ev.hands[int(p)] = _cards(v["resourceCards"].get("cards", []))
            if v and v.get("victoryPointsState"):
                ev.vp_state[int(p)] = {int(k): int(n) for k, n in v["victoryPointsState"].items() if n is not None}
        dev_players = ((sc.get("mechanicDevelopmentCardsState") or {}).get("players")) or {}
        for p, v in dev_players.items():
            bought = (v or {}).get("developmentCardsBoughtThisTurn")
            if bought:
                ev.dev_bought[int(p)] = [DevCard(c) for c in bought if c in DevCard._value2member_map_]
        rs = sc.get("mechanicRobberState") or {}
        if "locationTileIndex" in rs:
            ev.robber = int(rs["locationTileIndex"])
        for k, n in ((sc.get("bankState") or {}).get("resourceCards") or {}).items():
            ev.bank[Resource(int(k))] = int(n)

        if ev.ends_turn:
            pending.clear()
        events.append(ev)
        turn, current = next_turn, next_player

    _link_steals(events)
    return Replay(
        game_id=str(data.get("databaseGameId", "")),
        board=board,
        players=players,
        play_order=[int(x) for x in data.get("playOrder", [])],
        perspective=data.get("playerPerspective"),
        initial_robber=int(initial.get("mechanicRobberState", {}).get("locationTileIndex", -1)),
        initial_bank={Resource(int(k)): int(v) for k, v in initial["bankState"]["resourceCards"].items()},
        events=events,
        dev_draw_order=draw_order,
        total_turns=int(end.get("totalTurnCount", events[-1].next_turn if events else 0)),
        winner=winner,
    )


def _link_steals(events: list[Event]) -> None:
    open_move: RobberMove | None = None
    for ev in events:
        for a in ev.actions:
            if isinstance(a, RobberMove):
                open_move = a
            elif isinstance(a, Steal) and open_move is not None and open_move.player == a.thief:
                open_move.victim = a.victim
                open_move.card = a.card
                a.cause = open_move.cause
                open_move = None
            elif isinstance(a, Roll):
                open_move = None
        if ev.ends_turn:
            open_move = None
