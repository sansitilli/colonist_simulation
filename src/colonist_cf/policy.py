from __future__ import annotations

from dataclasses import dataclass

from .cards import Cards
from .constants import COST, DISCARD_LIMIT, RESOURCES, DevCard, Resource
from .replay import Build, DevBuy, Replay
from .trading import Trade, plan_trades


@dataclass(frozen=True)
class Goal:
    kind: str
    location: int | None = None

    def label(self) -> str:
        return self.kind if self.location is None else f"{self.kind} {self.location}"


def goal_cost(g: Goal) -> Cards:
    return Cards(COST[g.kind])


def recorded_goals(replay: Replay, hero: int, after_event: int) -> list[Goal]:
    goals: list[Goal] = []
    for ev in replay.events:
        if ev.index <= after_event:
            continue
        for a in ev.actions:
            if isinstance(a, DevBuy) and a.player == hero:
                goals.append(Goal("dev"))
            elif isinstance(a, Build) and a.player == hero and not a.free:
                goals.append(Goal(a.piece, a.location))
    return goals


class Policy:
    name = "base"

    def __init__(self, monopoly_threshold: int = 5, max_new_roads: int = 2, lookahead: int = 2):
        self.monopoly_threshold = monopoly_threshold
        self.max_new_roads = max_new_roads
        self.lookahead = lookahead

    def begin(self, view) -> None:
        pass

    def upcoming(self, view) -> list[Goal]:
        return []

    def need(self, view) -> Cards:
        total = Cards()
        for g in self.upcoming(view)[: self.lookahead]:
            total += goal_cost(g)
        return total

    def keep_weights(self, view) -> dict[Resource, float]:
        upcoming = self.upcoming(view)
        after = Cards()
        for g in upcoming[1 : 1 + self.lookahead]:
            after += goal_cost(g)
        return {r: 1.0 + 0.25 * after[r] for r in RESOURCES} if upcoming else {r: 1.0 for r in RESOURCES}

    def take_turn(self, view) -> None:
        self.play_development(view)
        self.purchase(view)
        self.manage_hand(view)

    def purchase(self, view) -> None:
        raise NotImplementedError

    def play_development(self, view) -> None:
        if view.playable(DevCard.KNIGHT) and view.robber_blocks_hero():
            view.play_knight()
            return
        upcoming = self.upcoming(view)
        if view.playable(DevCard.MONOPOLY):
            r = self.monopoly_choice(view, upcoming)
            if r is not None:
                view.play_monopoly(r)
                return
        if view.playable(DevCard.YEAR_OF_PLENTY) and upcoming:
            pick = self.year_of_plenty_choice(view, upcoming[0])
            if pick is not None:
                view.play_year_of_plenty(*pick)
                return
        if view.playable(DevCard.ROAD_BUILDING):
            edges = self.road_building_choice(view)
            if edges:
                view.play_road_building(edges)

    def monopoly_choice(self, view, upcoming: list[Goal]) -> Resource | None:
        hand = view.hand
        ratios = view.ratios()
        first = goal_cost(upcoming[0]) if upcoming else Cards()
        need = self.need(view)
        best: tuple[float, Resource] | None = None
        for r in RESOURCES:
            gain = view.opponents_holding(r)
            if gain <= 0:
                continue
            direct = min(gain, max(0, need[r] - hand[r]))
            value = direct + (gain - direct) / ratios[r]
            after = hand.copy()
            after.add(r, gain)
            enables = upcoming and plan_trades(after, first, ratios, view.bank()) is not None
            already = upcoming and view.plan(first) is not None
            if (enables and not already) or gain >= self.monopoly_threshold:
                if best is None or value > best[0]:
                    best = (value, r)
        return best[1] if best else None

    def year_of_plenty_choice(self, view, goal: Goal) -> tuple[Resource, Resource] | None:
        hand = view.hand
        deficit = hand.deficit(goal_cost(goal)).as_list()
        bank = view.bank()
        picks = [r for r in deficit if bank[r] > 0][:2]
        if not picks:
            return None
        if len(picks) == 1:
            picks.append(picks[0] if bank[picks[0]] > 1 else max(RESOURCES, key=lambda x: bank[x]))
        return picks[0], picks[1]

    def road_building_choice(self, view) -> list[int]:
        if view.pieces_left("settlement") < 1:
            return []
        options = [o for o in view.settlement_options(self.max_new_roads) if o[1]]
        if not options:
            return []
        corner, path = max(options, key=lambda o: (view.board.corner_pips(o[0]), -len(o[1])))
        return path[:2]

    def manage_hand(self, view) -> None:
        guard = 0
        while view.hand.total() > DISCARD_LIMIT and guard < 10:
            guard += 1
            hand = view.hand
            need = self.need(view)
            ratios = view.ratios()
            bank = view.bank()
            deficit = hand.deficit(need)
            targets = [r for r in RESOURCES if deficit[r] > 0 and bank[r] > 0]
            if not targets:
                break
            surplus = hand.surplus(need)
            sources = [r for r in RESOURCES if surplus[r] >= ratios[r]]
            if not sources:
                break
            give = min(sources, key=lambda r: (ratios[r], -surplus[r]))
            get = max(targets, key=lambda r: deficit[r])
            view.trade(Trade(give, ratios[give], get))

    def discard(self, view, n: int) -> Cards:
        hand = view.hand
        reserved = Cards()
        pool = hand.copy()
        for g in self.upcoming(view)[: self.lookahead]:
            c = goal_cost(g)
            for r in RESOURCES:
                take = min(pool[r], c[r])
                reserved.add(r, take)
                pool.add(r, -take)
        ratios = view.ratios()
        out = Cards()
        while out.total() < n and pool.total() > 0:
            r = max((r for r in RESOURCES if pool[r] > 0), key=lambda r: (ratios[r], pool[r]))
            pool.add(r, -1)
            out.add(r, 1)
        later = list(reversed(self.upcoming(view)[: self.lookahead]))
        for g in later:
            c = goal_cost(g)
            for r in RESOURCES:
                while out.total() < n and c[r] > 0 and reserved[r] > 0:
                    reserved.add(r, -1)
                    c.add(r, -1)
                    out.add(r, 1)
        while out.total() < n:
            r = max((r for r in RESOURCES if reserved[r] > 0), key=lambda r: reserved[r])
            reserved.add(r, -1)
            out.add(r, 1)
        return out


class ScriptedPolicy(Policy):
    name = "scripted"

    def __init__(self, goals: list[Goal], **kw):
        super().__init__(**kw)
        self.goals = list(goals)
        self.i = 0
        self.fallback = GreedyPolicy(**kw)

    def _skip_done(self, view) -> None:
        while self.i < len(self.goals):
            g = self.goals[self.i]
            corners = view.hero_corners()
            if g.kind == "city":
                if corners.get(g.location) == "settlement":
                    return
                alt = self._best_city_target(view)
                if alt is not None and view.pieces_left("city") > 0:
                    self.goals[self.i] = Goal("city", alt)
                    return
                self.i += 1
                continue
            if g.kind == "settlement" and g.location is not None and g.location in corners:
                self.i += 1
                continue
            if g.kind == "road" and g.location is not None and not view.road_legal(g.location):
                self.i += 1
                continue
            if g.kind == "dev" and view.deck_remaining() <= 0:
                self.i += 1
                continue
            return

    def _best_city_target(self, view) -> int | None:
        options = [c for c, k in view.hero_corners().items() if k == "settlement"]
        return max(options, key=view.board.corner_pips) if options else None

    def upcoming(self, view) -> list[Goal]:
        self._skip_done(view)
        rest = self.goals[self.i :]
        return rest if rest else self.fallback.upcoming(view)

    def purchase(self, view) -> None:
        while True:
            self._skip_done(view)
            if self.i >= len(self.goals):
                self.fallback.purchase(view)
                return
            g = self.goals[self.i]
            keep = self.keep_weights(view)
            ok = False
            if g.kind == "dev":
                ok = view.buy_dev(keep)
            elif g.kind == "city":
                ok = view.build_city(g.location, keep)
            elif g.kind == "settlement":
                ok = view.build_settlement(g.location, None, keep)
                if not ok:
                    for c, path in view.settlement_options(self.max_new_roads):
                        if c == g.location:
                            ok = view.build_settlement(c, path, keep)
                            break
            elif g.kind == "road":
                ok = view.build_road(g.location, keep)
            if not ok:
                return
            self.i += 1


class GreedyPolicy(Policy):
    name = "adaptive"

    def _city_target(self, view) -> int | None:
        options = [c for c, k in view.hero_corners().items() if k == "settlement"]
        if not options or view.pieces_left("city") < 1:
            return None
        return max(options, key=view.board.corner_pips)

    def _settlement_target(self, view):
        if view.pieces_left("settlement") < 1:
            return None
        options = view.settlement_options(self.max_new_roads)
        if not options:
            return None
        return max(options, key=lambda o: (view.board.corner_pips(o[0]) - 2 * len(o[1]), -len(o[1])))

    def upcoming(self, view) -> list[Goal]:
        goals: list[Goal] = []
        city = self._city_target(view)
        if city is not None:
            goals.append(Goal("city", city))
        target = self._settlement_target(view)
        if target is not None:
            goals.append(Goal("settlement", target[0]))
        if view.deck_remaining() > 0:
            goals.append(Goal("dev"))
        return goals

    def purchase(self, view) -> None:
        progress = True
        while progress:
            progress = False
            keep = self.keep_weights(view)
            city = self._city_target(view)
            if city is not None and view.build_city(city, keep):
                progress = True
                continue
            target = self._settlement_target(view)
            if target is not None and view.build_settlement(target[0], target[1], keep):
                progress = True
                continue
            if view.deck_remaining() > 0 and view.buy_dev(keep):
                progress = True


def make_policy(spec: dict, replay: Replay, hero: int, decision_end: int) -> Policy:
    name = spec.get("name", "scripted")
    kw = {k: spec[k] for k in ("monopoly_threshold", "max_new_roads", "lookahead") if k in spec}
    if name in ("adaptive", "greedy"):
        return GreedyPolicy(**kw)
    if name == "scripted":
        goals = spec.get("goals", "recorded")
        if goals == "recorded":
            parsed = recorded_goals(replay, hero, decision_end)
        else:
            parsed = [Goal(g["kind"], g.get("location")) for g in goals]
        return ScriptedPolicy(parsed, **kw)
    raise ValueError(f"unknown policy {name}")


def make_opponent_policy(spec: dict) -> Policy:
    kw = {k: spec[k] for k in ("monopoly_threshold", "max_new_roads", "lookahead") if k in spec}
    if spec.get("name", "adaptive") not in ("adaptive", "greedy"):
        raise ValueError("opponents support only the adaptive policy")
    return GreedyPolicy(**kw)
