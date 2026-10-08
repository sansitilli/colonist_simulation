from colonist_cf.cards import Cards
from colonist_cf.constants import COST, Resource
from colonist_cf.trading import plan_trades

BANK = {r: 19 for r in Resource}


def test_already_affordable():
    assert plan_trades(Cards((0, 0, 0, 2, 3)), Cards(COST["city"]), {r: 4 for r in Resource}, BANK) == []


def test_uses_cheapest_port():
    ratios = {r: 4 for r in Resource} | {Resource.GRAIN: 2, Resource.LUMBER: 3}
    plan = plan_trades(Cards((3, 0, 0, 4, 2)), Cards(COST["city"]), ratios, BANK)
    assert len(plan) == 1 and plan[0].give == Resource.GRAIN and plan[0].ratio == 2


def test_impossible():
    assert plan_trades(Cards((1, 0, 0, 0, 0)), Cards(COST["city"]), {r: 4 for r in Resource}, BANK) is None


def test_bank_shortage():
    bank = BANK | {Resource.ORE: 0}
    assert plan_trades(Cards((8, 0, 0, 2, 2)), Cards(COST["city"]), {r: 4 for r in Resource}, bank) is None
