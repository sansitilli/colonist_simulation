from __future__ import annotations

import json
from pathlib import Path

COLOUR = {1: "Red", 2: "Blue", 3: "Orange", 4: "Green", 5: "Black", 6: "White", 7: "Purple", 8: "Brown"}
PRIVATE_KEYS = ("userId", "countryCode", "regionUpdated", "membership", "databaseIcon", "deviceType")


def anonymize(src: str | Path, dst: str | Path, keep: list[str] | None = None) -> dict[str, str]:
    keep_lower = {k.lower() for k in keep or []}
    raw = json.loads(Path(src).read_text())
    data = raw.get("data", raw)
    renamed: dict[str, str] = {}
    for u in data.get("playerUserStates", []):
        name = u.get("username", "")
        if name.lower() not in keep_lower:
            new = COLOUR.get(int(u.get("selectedColor", 0)), f"Player{u.get('selectedColor')}")
            renamed[name] = new
            u["username"] = new
        for k in PRIVATE_KEYS:
            u.pop(k, None)
    history = data.get("eventHistory", {})
    for e in history.get("events", []):
        e.get("stateChange", {}).pop("gameChatState", None)
    if "initialState" in history:
        history["initialState"]["gameChatState"] = {}
    data.get("gameSettings", {}).pop("id", None)
    text = json.dumps(raw, separators=(",", ":"))
    for old in renamed:
        if len(old) > 3 and f'"{old}"' in text:
            raise ValueError(f"username {old} still present after anonymization")
    Path(dst).write_text(text)
    return renamed
