from __future__ import annotations

from typing import Iterable

from .constants import RESOURCES, SYMBOL, Resource


class Cards:
    __slots__ = ("v",)

    def __init__(self, values: Iterable[int] = (0, 0, 0, 0, 0)):
        self.v = list(values)

    @classmethod
    def of(cls, cards: Iterable[int]) -> "Cards":
        c = cls()
        for r in cards:
            c.v[int(r) - 1] += 1
        return c

    def copy(self) -> "Cards":
        return Cards(self.v)

    def __getitem__(self, r: int) -> int:
        return self.v[int(r) - 1]

    def __setitem__(self, r: int, n: int) -> None:
        self.v[int(r) - 1] = n

    def add(self, r: int, n: int = 1) -> None:
        self.v[int(r) - 1] += n

    def __add__(self, other: "Cards") -> "Cards":
        return Cards(a + b for a, b in zip(self.v, other.v))

    def __sub__(self, other: "Cards") -> "Cards":
        return Cards(a - b for a, b in zip(self.v, other.v))

    def __iadd__(self, other: "Cards") -> "Cards":
        for i in range(5):
            self.v[i] += other.v[i]
        return self

    def __isub__(self, other: "Cards") -> "Cards":
        for i in range(5):
            self.v[i] -= other.v[i]
        return self

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Cards) and self.v == other.v

    def __hash__(self) -> int:
        return hash(tuple(self.v))

    def total(self) -> int:
        return sum(self.v)

    def covers(self, other: "Cards") -> bool:
        return all(a >= b for a, b in zip(self.v, other.v))

    def deficit(self, need: "Cards") -> "Cards":
        return Cards(max(0, b - a) for a, b in zip(self.v, need.v))

    def surplus(self, need: "Cards") -> "Cards":
        return Cards(max(0, a - b) for a, b in zip(self.v, need.v))

    def is_valid(self) -> bool:
        return all(x >= 0 for x in self.v)

    def clamp(self) -> "Cards":
        return Cards(max(0, x) for x in self.v)

    def as_list(self) -> list[Resource]:
        out: list[Resource] = []
        for r in RESOURCES:
            out.extend([r] * self[r])
        return out

    def __repr__(self) -> str:
        return "".join(SYMBOL[r] * max(0, self[r]) for r in RESOURCES) or "-"
