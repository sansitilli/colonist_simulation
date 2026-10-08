from colonist_cf.audit import audit
from colonist_cf.constants import DevCard


def test_players_and_order(replay):
    assert replay.play_order == [3, 4, 5, 2]
    assert replay.name(4) == "Ushpuppy"
    assert replay.winner == 4


def test_every_hand_and_roll_reproduced(replay):
    for color in replay.play_order:
        rep = audit(replay, color)
        assert rep.ok, (color, rep.hand_mismatches[:3], rep.production_mismatches[:3], rep.dev_mismatches)
        assert rep.rolls == 54


def test_draw_order(replay):
    assert len(replay.dev_draw_order) == 16
    assert replay.dev_draw_order[-1] == DevCard.VICTORY_POINT
