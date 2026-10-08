from __future__ import annotations

import math
from dataclasses import dataclass

from .constants import NAME, PIPS, Resource

_SQ3 = math.sqrt(3)
_VERTEX_ANGLES = (0, 60, 120, 180, 240, 300)
_EDGE_SLOT = {0: 5, 1: 4, 2: 3}
GENERIC_PORT = 0


def _center(q: int, r: int) -> tuple[float, float]:
    return _SQ3 * (q + r / 2), 1.5 * r


def _key(x: float, y: float) -> tuple[float, float]:
    return round(x, 3) + 0.0, round(y, 3) + 0.0


def _hex_vertices(q: int, r: int) -> list[tuple[float, float]]:
    cx, cy = _center(q, r)
    return [
        _key(cx + math.sin(math.radians(a)), cy - math.cos(math.radians(a)))
        for a in _VERTEX_ANGLES
    ]


def _corner_point(x: int, y: int, z: int) -> tuple[float, float]:
    cx, cy = _center(x, y)
    return _key(cx, cy - 1 if z == 0 else cy + 1)


@dataclass(frozen=True)
class Tile:
    index: int
    q: int
    r: int
    resource: Resource | None
    number: int

    @property
    def pips(self) -> int:
        return PIPS.get(self.number, 0)

    def label(self) -> str:
        if self.resource is None:
            return "desert"
        return f"{NAME[self.resource]} {self.number}"


class Board:
    def __init__(
        self,
        tiles: dict[int, Tile],
        corner_tiles: dict[int, tuple[int, ...]],
        edge_corners: dict[int, tuple[int, int]],
        corner_ports: dict[int, int],
    ):
        self.tiles = tiles
        self.corner_tiles = corner_tiles
        self.edge_corners = edge_corners
        self.corner_ports = corner_ports
        self.corner_neighbors: dict[int, set[int]] = {c: set() for c in corner_tiles}
        self.corner_edges: dict[int, list[int]] = {c: [] for c in corner_tiles}
        self._edge_index: dict[frozenset[int], int] = {}
        for e, (a, b) in edge_corners.items():
            self.corner_neighbors[a].add(b)
            self.corner_neighbors[b].add(a)
            self.corner_edges[a].append(e)
            self.corner_edges[b].append(e)
            self._edge_index[frozenset((a, b))] = e
        self.tile_corners: dict[int, list[int]] = {t: [] for t in tiles}
        for c, ts in corner_tiles.items():
            for t in ts:
                self.tile_corners[t].append(c)

    @classmethod
    def from_map_state(cls, map_state: dict) -> "Board":
        tiles: dict[int, Tile] = {}
        for k, v in map_state["tileHexStates"].items():
            kind = int(v["type"])
            tiles[int(k)] = Tile(
                index=int(k),
                q=int(v["x"]),
                r=int(v["y"]),
                resource=Resource(kind) if kind in Resource._value2member_map_ else None,
                number=int(v.get("diceNumber", 0)),
            )

        point_to_corner: dict[tuple[float, float], int] = {}
        for k, v in map_state["tileCornerStates"].items():
            point_to_corner[_corner_point(v["x"], v["y"], v["z"])] = int(k)

        corner_tiles: dict[int, list[int]] = {c: [] for c in point_to_corner.values()}
        for t in tiles.values():
            for p in _hex_vertices(t.q, t.r):
                if p not in point_to_corner:
                    raise ValueError(f"tile {t.index} vertex {p} has no corner")
                corner_tiles[point_to_corner[p]].append(t.index)

        def edge_ends(x: int, y: int, z: int) -> tuple[int, int] | None:
            verts = _hex_vertices(x, y)
            i = _EDGE_SLOT[z]
            a, b = verts[i], verts[(i + 1) % 6]
            if a not in point_to_corner or b not in point_to_corner:
                return None
            return point_to_corner[a], point_to_corner[b]

        edge_corners: dict[int, tuple[int, int]] = {}
        for k, v in map_state["tileEdgeStates"].items():
            ends = edge_ends(v["x"], v["y"], v["z"])
            if ends is None:
                raise ValueError(f"edge {k} has an endpoint off the board")
            edge_corners[int(k)] = ends
        if len({frozenset(e) for e in edge_corners.values()}) != len(edge_corners):
            raise ValueError("edge orientation produced duplicate edges")

        corner_ports: dict[int, int] = {}
        for v in map_state.get("portEdgeStates", {}).values():
            ends = edge_ends(v["x"], v["y"], v["z"])
            if ends is None:
                raise ValueError("port edge has an endpoint off the board")
            kind = int(v["type"])
            port = GENERIC_PORT if kind == 1 else kind - 1
            for c in ends:
                corner_ports[c] = port

        return cls(
            tiles,
            {c: tuple(ts) for c, ts in corner_tiles.items()},
            edge_corners,
            corner_ports,
        )

    def edge_between(self, a: int, b: int) -> int | None:
        return self._edge_index.get(frozenset((a, b)))

    def corner_pips(self, corner: int) -> int:
        return sum(self.tiles[t].pips for t in self.corner_tiles[corner])

    def corner_label(self, corner: int) -> str:
        parts = [self.tiles[t].label() for t in self.corner_tiles[corner]]
        port = self.corner_ports.get(corner)
        if port is not None:
            parts.append("3:1 port" if port == GENERIC_PORT else f"{NAME[Resource(port)]} 2:1 port")
        return ", ".join(parts)

    def trade_ratios(self, corners: set[int]) -> dict[Resource, int]:
        ratios = {r: 4 for r in Resource}
        for c in corners:
            port = self.corner_ports.get(c)
            if port is None:
                continue
            if port == GENERIC_PORT:
                for r in Resource:
                    ratios[r] = min(ratios[r], 3)
            else:
                ratios[Resource(port)] = 2
        return ratios
