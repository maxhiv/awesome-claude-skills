"""Safety rails that wrap the agent loop.

Even in "fully autonomous" mode, these give you instant control without
editing code: a kill-switch file, a dry-run flag, and a per-tick action cap
that is both enforced in prompts and logged for audit.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Policy:
    dry_run: bool
    kill_switch_file: str
    max_actions_per_tick: int
    owner_emails: tuple[str, ...]
    reply_allowlist: tuple[str, ...]
    first_run_lookback_minutes: int
    handled_label: str

    @classmethod
    def from_env(cls) -> "Policy":
        def _csv(name: str) -> tuple[str, ...]:
            raw = os.environ.get(name, "").strip()
            return tuple(s.strip().lower() for s in raw.split(",") if s.strip())

        return cls(
            dry_run=os.environ.get("DRY_RUN", "0") == "1",
            kill_switch_file=os.environ.get("KILL_SWITCH_FILE", "PAUSE"),
            max_actions_per_tick=int(os.environ.get("MAX_ACTIONS_PER_TICK", "12")),
            owner_emails=_csv("OWNER_EMAILS"),
            reply_allowlist=_csv("REPLY_ALLOWLIST"),
            first_run_lookback_minutes=int(os.environ.get("FIRST_RUN_LOOKBACK_MINUTES", "60")),
            handled_label=os.environ.get("HANDLED_LABEL", "agent/handled"),
        )

    def paused(self) -> bool:
        return os.path.exists(self.kill_switch_file)
