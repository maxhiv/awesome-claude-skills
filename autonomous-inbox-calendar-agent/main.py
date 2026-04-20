"""Always-on polling loop entry point.

Run with `python main.py`. On Replit this is wired up via .replit — just
click Run, or deploy as a Background Worker for a real always-on process.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

import state
from agent import run_tick
from policy import Policy

load_dotenv()

_audit_handler = RotatingFileHandler(
    "audit.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), _audit_handler],
)
log = logging.getLogger("loop")

_REQUIRED_ENV = ("ANTHROPIC_API_KEY", "RUBE_MCP_URL", "RUBE_MCP_TOKEN")
_MAX_BACKOFF_SECONDS = 300

_stop = False


def _handle_sigterm(signum, _frame):
    global _stop
    log.info("received signal %s, will exit after current tick", signum)
    _stop = True


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)


def _require_env() -> None:
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"missing required env vars: {', '.join(missing)}")


def _responsive_sleep(seconds: int) -> None:
    """Sleep in 1s chunks so SIGTERM stays responsive."""
    for _ in range(max(0, seconds)):
        if _stop:
            return
        time.sleep(1)


def main() -> None:
    _require_env()

    from anthropic import Anthropic  # lazy so env errors surface first

    client = Anthropic()
    interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))
    backoff = interval

    log.info("agent starting; poll_interval=%ss", interval)

    while not _stop:
        policy = Policy.from_env()

        if policy.paused():
            log.info("kill-switch file %r present — sleeping", policy.kill_switch_file)
            _responsive_sleep(interval)
            continue

        st = state.load()
        is_first_run = not st.get("summaries")
        tick_start = time.monotonic()

        try:
            summary = run_tick(client, policy, state.memory_text(st), is_first_run)
        except Exception:
            log.exception("tick failed; backing off %ss", backoff)
            _responsive_sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
            continue

        backoff = interval  # reset backoff on success

        if summary:
            state.append_summary(st, summary)
            state.save(st)
            log.info("tick summary:\n%s", summary)
        else:
            log.warning("tick returned no text summary; memory unchanged")

        elapsed = int(time.monotonic() - tick_start)
        _responsive_sleep(max(1, interval - elapsed))

    log.info("agent stopped cleanly")


if __name__ == "__main__":
    main()
