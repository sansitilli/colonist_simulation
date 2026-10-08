from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from .constants import DECK_COMPOSITION, DevCard
from .replay import DevBuy, Replay


def undrawn_cards(drawn: list[DevCard]) -> list[DevCard]:
    left = Counter(DECK_COMPOSITION)
    left.subtract(Counter(drawn))
    if any(n < 0 for n in left.values()):
        raise ValueError("draw order exceeds the standard deck composition")
    return [c for c in DevCard for _ in range(left[c])]


def full_order(replay: Replay, known: list[int] | None, rng: random.Random) -> list[DevCard]:
    prefix = [DevCard(c) for c in known] if known else list(replay.dev_draw_order)
    tail = undrawn_cards(prefix)
    rng.shuffle(tail)
    return prefix + tail


@dataclass
class DrawRecord:
    event: int
    player: int
    position: int


def recorded_draws(replay: Replay) -> list[DrawRecord]:
    out: list[DrawRecord] = []
    for ev in replay.events:
        for a in ev.actions:
            if isinstance(a, DevBuy):
                out.append(DrawRecord(ev.index, a.player, a.draw_index))
    return out


@dataclass
class Deck:
    order: list[DevCard]
    hero: int
    start_event: int
    mode: str
    draws: list[DrawRecord]
    position: int = 0
    hero_drawn: int = 0
    _queue: list[DevCard] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.mode not in ("queue", "positional"):
            raise ValueError(f"unknown deck mode {self.mode}")
        self.position = sum(1 for d in self.draws if d.event < self.start_event)
        taken = {d.position for d in self.draws if d.player != self.hero or d.event < self.start_event}
        self._queue = [c for i, c in enumerate(self.order) if i not in taken]

    def remaining(self) -> int:
        if self.mode == "queue":
            return len(self._queue) - self.hero_drawn
        return len(self.order) - self.position

    def draw_hero(self) -> DevCard | None:
        if self.remaining() <= 0:
            return None
        self.hero_drawn += 1
        if self.mode == "queue":
            return self._queue[self.hero_drawn - 1]
        card = self.order[self.position]
        self.position += 1
        return card

    def draw_opponent(self, recorded: DevCard | None) -> DevCard | None:
        if self.mode == "queue":
            return recorded
        if self.position >= len(self.order):
            return None
        card = self.order[self.position]
        self.position += 1
        return card
