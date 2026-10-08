from enum import IntEnum


class Resource(IntEnum):
    LUMBER = 1
    BRICK = 2
    WOOL = 3
    GRAIN = 4
    ORE = 5


RESOURCES = tuple(Resource)

SYMBOL = {
    Resource.LUMBER: "L",
    Resource.BRICK: "B",
    Resource.WOOL: "W",
    Resource.GRAIN: "G",
    Resource.ORE: "O",
}

NAME = {
    Resource.LUMBER: "lumber",
    Resource.BRICK: "brick",
    Resource.WOOL: "wool",
    Resource.GRAIN: "grain",
    Resource.ORE: "ore",
}

ALIASES = {
    "wood": Resource.LUMBER,
    "wheat": Resource.GRAIN,
    "sheep": Resource.WOOL,
    "rock": Resource.ORE,
    "clay": Resource.BRICK,
}

BY_NAME = {v: k for k, v in NAME.items()} | ALIASES


class DevCard(IntEnum):
    KNIGHT = 11
    VICTORY_POINT = 12
    MONOPOLY = 13
    ROAD_BUILDING = 14
    YEAR_OF_PLENTY = 15


DECK_COMPOSITION = {
    DevCard.KNIGHT: 14,
    DevCard.VICTORY_POINT: 5,
    DevCard.MONOPOLY: 2,
    DevCard.ROAD_BUILDING: 2,
    DevCard.YEAR_OF_PLENTY: 2,
}


class Piece(IntEnum):
    ROAD = 0
    SETTLEMENT = 2
    CITY = 3


class Log(IntEnum):
    DEV_BOUGHT = 1
    PLACED_FREE = 4
    BUILT = 5
    ROLL = 10
    ROBBER_MOVED = 11
    STOLE_VICTIM_VIEW = 14
    STOLE_THIEF_VIEW = 15
    STOLE_PUBLIC = 16
    DEV_PLAYED = 20
    YEAR_OF_PLENTY = 21
    GOT_RESOURCES = 47
    DISCARDED = 55
    MONOPOLY = 86
    PLAYER_TRADE = 115
    BANK_TRADE = 116


SETUP_DISTRIBUTION = 0
ROLL_DISTRIBUTION = 1

COST = {
    "road": (1, 1, 0, 0, 0),
    "settlement": (1, 1, 1, 1, 0),
    "city": (0, 0, 0, 2, 3),
    "dev": (0, 0, 1, 1, 1),
}

PIECE_LIMIT = {"road": 15, "settlement": 5, "city": 4}
DISCARD_LIMIT = 7
VICTORY_POINTS_TO_WIN = 10
PIPS = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}
