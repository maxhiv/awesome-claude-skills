# Autonomous Inbox + Calendar Agent

An always-on Claude agent that triages Gmail, Outlook, Google Calendar, and
Slack on a polling loop. It replies, archives, schedules, and labels
autonomously. Built on:

- **Anthropic** — Claude (Sonnet 4.6 by default) with the MCP connector
- **Composio + Rube** — [Rube](https://rube.app) is Composio's universal MCP
  server. One OAuth dance there gives the agent tools for Gmail, Google
  Calendar, Outlook, and Slack.
- **Replit** — always-on Repl as the runtime

> ⚠️ **Fully autonomous mode is the default.** The agent will send mail,
> accept meetings, and act on Slack without asking. Safety rails below
> (`DRY_RUN`, `PAUSE` kill-switch, per-tick action cap) let you throttle or
> stop it instantly.

---

## Architecture

```
┌──────────────────────┐       ┌──────────────┐       ┌──────────────────┐
│  Replit always-on    │──────▶│ Anthropic API│──────▶│ Rube MCP server  │
│  main.py polling loop│       │  Claude 4.6  │◀──────│ (Composio)       │
│  (policy + state)    │◀──────│  + MCP conn  │       │ Gmail / GCal /   │
└──────────────────────┘       └──────────────┘       │ Outlook / Slack  │
                                                      └──────────────────┘
```

Each tick:
1. `main.py` checks the kill-switch + loads `Policy` from env.
2. `agent.run_tick()` calls Claude once with `mcp_servers=[rube]`.
3. Claude discovers Rube's tools, pulls new items, triages, and acts.
4. Claude emits a short plain-text summary; we persist it as memory for the
   next tick.
5. Sleep `POLL_INTERVAL_SECONDS`, repeat.

There is no custom tool-schema code in this repo — all tool definitions live
on Rube's side. That's the whole point of the MCP connector.

---

## One-time setup

### 1. Connect your apps on Rube

1. Go to <https://rube.app> and sign in.
2. Connect **Gmail**, **Google Calendar**, **Outlook / Microsoft 365**, and
   **Slack** (OAuth flows for each).
3. Copy your MCP server URL and bearer token from the Rube dashboard. They
   look like `https://rube.app/mcp` and a long opaque string.

### 2. Get an Anthropic API key

<https://console.anthropic.com> → API Keys → Create.

### 3. Create a Replit project

1. On <https://replit.com>, import this folder as a new Python Repl (or
   create a blank Python Repl and paste these files in).
2. Open the **Secrets** tab and add, one per row:
   - `ANTHROPIC_API_KEY`
   - `RUBE_MCP_URL` (e.g. `https://rube.app/mcp`)
   - `RUBE_MCP_TOKEN`
   - `OWNER_EMAILS` (comma-separated — your own addresses)
   - Optional: `ANTHROPIC_MODEL`, `POLL_INTERVAL_SECONDS`,
     `MAX_ACTIONS_PER_TICK`, `REPLY_ALLOWLIST`, `DRY_RUN`
3. Click **Run**. Watch the console — first tick happens immediately.

For a genuinely always-on process (surviving restarts), deploy as a
**Background Worker Deployment** on Replit rather than the free Run button.

### 4. First-run recommendation: start in DRY_RUN

Set `DRY_RUN=1` for the first day. The agent will plan everything but won't
send or schedule. Read `audit.log` and the per-tick summaries. When you're
confident, flip to `DRY_RUN=0`.

---

## Safety rails

| Control | How |
| --- | --- |
| Pause instantly | `touch PAUSE` in the Repl shell — the loop sleeps until you `rm PAUSE`. |
| Dry run | Set `DRY_RUN=1` in Secrets; redeploy. Agent drafts but does not act. |
| Action cap | `MAX_ACTIONS_PER_TICK` (default 12) — enforced in the prompt. |
| Never-mail-self | `OWNER_EMAILS` — the agent is instructed to never send to these. |
| Audit trail | Every tick is logged to `audit.log` with tool-use counts + token usage + the model's own summary. |
| Backoff on failure | One-shot exceptions double the sleep interval (capped at 5m). |

### Running locally (outside Replit)

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in .env
python main.py
```

---

## Files

- `main.py` — polling loop, signal handling, env checks
- `agent.py` — single-tick Claude call with Rube MCP wired in
- `prompts.py` — system prompt (triage rules, safety constraints, memory)
- `policy.py` — env-driven safety config
- `state.py` — JSON-backed memory of previous tick's summary
- `.replit`, `replit.nix` — Replit runtime config
- `.env.example` — every env var documented

---

## Tuning

- **Latency vs cost** — `POLL_INTERVAL_SECONDS=60` ≈ 1,440 ticks/day. If
  you're on Sonnet 4.6 with modest inboxes that's typically a few USD/day.
  Raise the interval or move to webhook-driven triggers (Rube supports
  them) to drop cost.
- **Smarter triage** — swap `ANTHROPIC_MODEL=claude-opus-4-7` for harder
  scheduling negotiations. Cost goes up roughly 5×.
- **Narrower scope** — edit `prompts.py`. The whole behavior lives there.

---

## Known limits

- Rube tool availability depends on what Composio exposes for each app at
  the time you run this. If a tool you expect isn't there, check the Rube
  dashboard's tool list.
- The agent's "memory" is just the last tick's summary. For longer memory,
  swap `state.py` for a vector store or append-only log fed back into the
  prompt.
- No test suite. This is a small operational script — verify behavior in
  `DRY_RUN=1` first, not with unit tests.
