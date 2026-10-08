from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .cards import Cards
from .constants import RESOURCES, Resource


@dataclass(frozen=True)
class Trade:
    give: Resource
    ratio: int
    get: Resource


def plan_trades(
    hand: Cards,
    need: Cards,
    ratios: Mapping[Resource, int],
    bank: Mapping[Resource, int],
    keep_weight: Mapping[Resource, float] | None = None,
) -> list[Trade] | None:
    if hand.covers(need):
        return []
    deficit = hand.deficit(need)
    for r in RESOURCES:
        if deficit[r] > bank.get(r, 0):
            return None
    targets = deficit.as_list()
    surplus = hand.surplus(need)
    caps = {r: surplus[r] // ratios[r] for r in RESOURCES}
    if sum(caps.values()) < len(targets):
        return None
    weight = keep_weight or {}
    order = sorted(RESOURCES, key=lambda r: (ratios[r] * weight.get(r, 1.0), ratios[r]))
    best: tuple[float, dict[Resource, int]] | None = None

    def search(i: int, left: int, chosen: dict[Resource, int], cost: float) -> None:
        nonlocal best
        if best is not None and cost >= best[0]:
            return
        if left == 0:
            best = (cost, dict(chosen))
            return
        if i == len(order):
            return
        r = order[i]
        for n in range(min(caps[r], left), -1, -1):
            chosen[r] = n
            search(i + 1, left - n, chosen, cost + n * ratios[r] * weight.get(r, 1.0))
        chosen.pop(r, None)

    search(0, len(targets), {}, 0.0)
    if best is None:
        return None
    trades: list[Trade] = []
    sources = [r for r in order for _ in range(best[1].get(r, 0))]
    for give, get in zip(sources, targets):
        trades.append(Trade(give, ratios[give], get))
    return trades


def trades_cost(trades: list[Trade]) -> Cards:
    out = Cards()
    for t in trades:
        out.add(t.give, t.ratio)
        out.add(t.get, -1)
    return out
