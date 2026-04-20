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

from dotenv import load_dotenv

import state
from agent import run_tick
from policy import Policy

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("audit.log"),
    ],
)
log = logging.getLogger("loop")

_stop = False


def _handle_sigterm(signum, _frame):
    global _stop
    log.info("received signal %s, will exit after current tick", signum)
    _stop = True


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)


def _require_env() -> None:
    missing = [k for k in ("ANTHROPIC_API_KEY", "RUBE_MCP_URL") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"missing required env vars: {', '.join(missing)}")


def main() -> None:
    _require_env()

    # Import lazily so missing-env errors surface first with a clean message.
    from anthropic import Anthropic

    client = Anthropic()
    interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))

    log.info("agent starting; poll_interval=%ss", interval)

    while not _stop:
        policy = Policy.from_env()

        if policy.paused():
            log.info("kill-switch file %r present — sleeping", policy.kill_switch_file)
            time.sleep(interval)
            continue

        st = state.load()
        try:
            summary = run_tick(client, policy, st.get("last_summary", ""))
        except Exception:
            log.exception("tick failed; backing off")
            time.sleep(min(interval * 2, 300))
            continue

        if summary:
            st["last_summary"] = summary
            state.save(st)
            log.info("tick summary:\n%s", summary)

        # Sleep in 1s chunks so SIGTERM is responsive.
        for _ in range(interval):
            if _stop:
                break
            time.sleep(1)

    log.info("agent stopped cleanly")


if __name__ == "__main__":
    main()
