"""Tiny JSON-backed state store so the agent doesn't re-process items.

The agent itself writes a short natural-language summary at the end of each
tick; we persist it and feed it back in on the next tick as memory. We also
track the last-processed timestamp per source to bound the work window.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

STATE_PATH = os.environ.get("STATE_FILE", "state.json")


def load() -> dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return {"last_summary": "", "cursors": {}, "updated_at": 0}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"last_summary": "", "cursors": {}, "updated_at": 0}


def save(state: dict[str, Any]) -> None:
    state["updated_at"] = int(time.time())
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)
