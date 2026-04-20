"""Tiny JSON-backed state store so the agent doesn't re-process items.

We keep a rolling window of the last N tick summaries (N=3) as memory. More
than one gives the model continuity across short gaps without blowing up
token cost; capping prevents unbounded growth.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

STATE_PATH = os.environ.get("STATE_FILE", "state.json")
MAX_SUMMARIES = 3


def load() -> dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return {"summaries": [], "updated_at": 0}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"summaries": [], "updated_at": 0}

    # Back-compat: older file used `last_summary: str`. Upgrade in place.
    if "summaries" not in data:
        legacy = data.get("last_summary", "")
        data = {"summaries": [legacy] if legacy else [], "updated_at": data.get("updated_at", 0)}
    return data


def save(state: dict[str, Any]) -> None:
    state["updated_at"] = int(time.time())
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def append_summary(state: dict[str, Any], summary: str) -> None:
    summaries = state.setdefault("summaries", [])
    summaries.append(summary)
    del summaries[:-MAX_SUMMARIES]


def memory_text(state: dict[str, Any]) -> str:
    summaries = state.get("summaries") or []
    if not summaries:
        return ""
    blocks = [f"--- tick -{len(summaries) - i} ---\n{s}" for i, s in enumerate(summaries)]
    return "\n\n".join(blocks)
