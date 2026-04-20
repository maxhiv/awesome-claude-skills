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
   **Slack** (OAuth flows for each). Optional but high-leverage extras —
   connect these too and the agent will use them when relevant: **Calendly**
   (scheduling links), **Zoom** / **Google Meet** (auto-create join links),
   **Notion** (drop meeting notes), **Linear** (ticket refs from mail/Slack).
3. Copy your MCP server URL and bearer token from the Rube dashboard. They
   look like `https://rube.app/mcp` and a long opaque string.

#### Scoping Rube to just the apps you want (recommended)

By default the Rube MCP URL can reach any toolkit you've connected. For
defense-in-depth — so a prompt-injection email can't trick the agent into
using GitHub or Stripe — create a **Custom MCP Server** scoped to just mail,
calendar, and chat:

```bash
curl -X POST https://backend.composio.dev/api/v3/mcp/servers/custom \
  -H "Authorization: Bearer $COMPOSIO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "inbox-calendar-agent",
    "toolkits": ["GMAIL", "GOOGLECALENDAR", "OUTLOOK", "SLACK"]
  }'
```

Use the returned URL as `RUBE_MCP_URL`. See
<https://docs.composio.dev/reference/api-reference/mcp/postMcpServersCustom>.

#### Multi-account (e.g. 2 Gmails)

Rube binds tools to the most recently connected account of each type. If
you have multiple Gmail accounts, the clean pattern is one Custom MCP URL
per account (created with distinct `user_id` / `auth_config_id`), then run
one instance of this agent per URL.

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
| Action cap | `MAX_ACTIONS_PER_TICK` (default 12) — enforced in the prompt; a WARNING is logged if the model exceeds it. |
| Never-mail-self | `OWNER_EMAILS` — the agent is instructed to never send to these. |
| Cold-start bound | `FIRST_RUN_LOOKBACK_MINUTES` (default 60) so the first tick doesn't try to triage weeks of backlog. |
| Dedupe label | `HANDLED_LABEL` (default `agent/handled`) — the agent labels what it touches and excludes that label on the next scan. |
| Audit trail | Rotating `audit.log` (5MB × 3) with tool-use names + truncated inputs + token usage + the model's own summary. |
| Backoff on failure | Exceptions double the sleep interval (capped at 5m); resets on the first successful tick. |
| Stable cadence | The loop subtracts actual tick duration from the sleep so a slow tick doesn't drift the cadence. |

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

- **Cost — prompt caching is on.** The system prompt is split into a static
  cacheable block and a dynamic block, so after the first tick in a 5-minute
  window subsequent ticks read the cached prefix at 10% of base token cost.
  Watch `cache_read` / `cache_write` in `audit.log`. Caching only activates
  once the cached prefix (system + Rube's MCP tool defs) crosses 2,048
  tokens; with a scoped Rube URL that typically happens immediately.
- **Latency vs cost** — `POLL_INTERVAL_SECONDS=60` ≈ 1,440 ticks/day. If
  you're on Sonnet 4.6 with modest inboxes that's typically a few USD/day.
  Raise the interval to drop cost proportionally.
- **Smarter scheduling** — set `THINKING_BUDGET_TOKENS=8000` to enable
  extended thinking. Worth it if the agent is regularly negotiating meetings
  across 3+ people's calendars. Keep the value stable (changes invalidate
  the prompt cache).
- **Bigger model per tick** — swap `ANTHROPIC_MODEL=claude-opus-4-7`. Cost
  goes up ~5×; usually not needed.
- **Narrower scope** — edit `prompts.py`. The whole behavior lives there.

---

## Auth expiry

Composio auto-refreshes OAuth tokens. When a refresh finally fails (revoked
consent, password reset, MFA change) the agent sees a `401` /
`CONNECTION_EXPIRED` from Rube. The loop detects this, logs `AUTH_EXPIRED`
at ERROR level naming the toolkit, and the model's end-of-tick summary
includes an `AUTH_EXPIRED: <toolkit>` line. Re-authenticate on
<https://rube.app> and the next tick resumes automatically.

## Known limits

- Rube tool availability depends on what Composio exposes for each app at
  the time you run this. If a tool you expect isn't there, check the Rube
  dashboard's tool list.
- Memory is the last 3 tick summaries + mail's `HANDLED_LABEL`. That's
  enough for continuity across short gaps but not a long-term knowledge
  base. For "what did I tell Acme about pricing last March?" you'd want a
  vector index over sent mail — out of scope here.
- Claude's built-in Memory tool is not used: it requires the Managed Agents
  API, while this project uses the Messages API for the polling loop.
- No test suite. This is a small operational script — verify behavior in
  `DRY_RUN=1` first, not with unit tests.
