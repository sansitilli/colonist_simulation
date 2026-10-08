from colonist_cf.board import GENERIC_PORT
from colonist_cf.constants import Resource


def test_geometry_counts(replay):
    b = replay.board
    assert len(b.tiles) == 19
    assert len(b.corner_tiles) == 54
    assert len(b.edge_corners) == 72
    assert len(set(b.corner_ports)) == 18


def test_port_corners(replay):
    b = replay.board
    assert b.corner_ports[9] == Resource.LUMBER
    assert b.corner_ports[39] == Resource.GRAIN
    assert b.corner_ports[35] == GENERIC_PORT


def test_decision_corners(replay):
    b = replay.board
    assert [b.tiles[t].label() for t in b.corner_tiles[9]] == ["wool 10"]
    assert [b.tiles[t].label() for t in b.corner_tiles[39]] == ["ore 3"]
    assert 41 in b.corner_neighbors[38]
    assert b.edge_between(8, 9) is not None
    assert b.edge_between(34, 39) is not None


def test_trade_ratios(replay):
    r = replay.board.trade_ratios({35, 39})
    assert r[Resource.GRAIN] == 2
    assert r[Resource.ORE] == 3
