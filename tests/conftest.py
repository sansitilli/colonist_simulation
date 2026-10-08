from pathlib import Path

import pytest

from colonist_cf.replay import load
from colonist_cf.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def replay():
    return load(ROOT / "data" / "game_256800428.json")


@pytest.fixture()
def scenario():
    return load_scenario(ROOT / "scenarios" / "ushpuppy_port_choice.json")
