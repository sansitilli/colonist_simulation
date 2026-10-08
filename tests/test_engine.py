import pytest

from colonist_cf.engine import Branch
from colonist_cf.fullgame import FullGame
from colonist_cf.oracle import search
from colonist_cf.policy import GreedyPolicy
from colonist_cf.scenario import make_engine, simulate


def branch(sc, name):
    return next(b for b in sc.branches if b.name == name)


def test_recorded_plan_reproduces_actual_win(scenario):
    scenario.deck_mode = "queue"
    o = simulate(scenario, branch(scenario, "wood_port"), 1, policy={"name": "scripted"})
    assert o.winner == scenario.hero and o.win_turn == 77 and o.won_in_record


def test_branches_cost_the_same(scenario):
    hands = []
    for b in scenario.branches:
        e = make_engine(scenario, b, 0)
        e.begin()
        hands.append(e.hand)
    assert hands[0] == hands[1]


def test_illegal_branch_rejected(scenario):
    bad = Branch("bad", roads=[(39, 38)], settlements=[38])
    with pytest.raises(ValueError):
        make_engine(scenario, bad, 0).run()


def test_runs_are_deterministic(scenario):
    b = branch(scenario, "grain_port")
    a, c = simulate(scenario, b, 7), simulate(scenario, b, 7)
    assert (a.winner, a.winner_turn, a.log) == (c.winner, c.winner_turn, c.log)


def test_handoff_preserves_victory_points(scenario):
    for b in scenario.branches:
        for seed in range(5):
            e = make_engine(scenario, b, seed)
            e.continue_turns = 0
            e.run()
            if e.won_turn or e.lost_to:
                continue
            last = e.replay.events[-1]
            g = FullGame(e, {p: GreedyPolicy() for p in e.order}, seed, last.turn + 1, 5)
            for p in e.order:
                assert g.vp(p) == (e.vp() if p == e.hero else e.opp_vp(p))


def test_full_game_always_ends(scenario):
    o = simulate(scenario, branch(scenario, "wood_port"), 3, from_decision=True)
    assert o.winner is not None


def test_oracle_grain_beats_wood_positional(scenario):
    scenario.deck_mode = "positional"
    wood = search(scenario, branch(scenario, "wood_port"), 1, beam=60)
    grain = search(scenario, branch(scenario, "grain_port"), 1, beam=60)
    assert grain.win_turn == 69
    assert wood.win_turn is None or wood.win_turn > grain.win_turn


def test_recorded_rolls_cover_the_record(scenario):
    rolls = scenario.replay.recorded_rolls()
    assert sorted(rolls) == list(range(8, 78))
    assert rolls[46] == 11 and rolls[77] == 8


def test_recorded_dice_reach_the_engine(scenario):
    from colonist_cf.fullgame import FullGame

    b = branch(scenario, "grain_port")
    e = make_engine(scenario, b, 0)
    e.begin()
    seen = []
    g = FullGame(e, {p: GreedyPolicy() for p in e.order}, 0, e.turn + 1, 5, scenario.replay.recorded_rolls())
    original = g._produce

    def spy(total):
        seen.append((g.turn, total))
        original(total)

    g._produce = spy
    g.run(8)
    rolls = scenario.replay.recorded_rolls()
    assert all(rolls[t] == total for t, total in seen)
