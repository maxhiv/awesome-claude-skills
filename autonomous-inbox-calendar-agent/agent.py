"""Single-tick agent run: one Claude call with Rube MCP wired in.

We use Anthropic's MCP connector so Claude can discover and invoke Rube's
tools directly — no manual tool-schema plumbing in this file. The model
loops through tool_use / mcp_tool_result turns on the server side until it
emits a final text block; we return that text as the tick summary.

System prompt is split into a cacheable static block + a dynamic block so
prompt caching hits across ticks once the cached prefix (system + MCP
tool defs returned by Rube) crosses Anthropic's 2,048-token minimum.
"""
from __future__ import annotations

import json
import logging
import os
import re

from anthropic import Anthropic

from policy import Policy
from prompts import dynamic_context, static_rules

log = logging.getLogger("agent")

_MCP_BETA = "mcp-client-2025-04-04"
_MAX_TOKENS = 8192
_AUDIT_INPUT_CHARS = 240  # truncate tool_use inputs in the audit log

_MUTATING_HINTS = (
    "send", "reply", "forward", "create", "update", "delete", "archive",
    "trash", "accept", "decline", "post", "move", "insert",
)
_AUTH_ERROR_PATTERN = re.compile(
    r"\b(401|unauthor(i[sz]ed)?|connection[_ ]expired|invalid[_ ]grant|token[_ ]expired)\b",
    re.IGNORECASE,
)


def _mcp_servers() -> list[dict]:
    url = os.environ["RUBE_MCP_URL"]
    token = os.environ["RUBE_MCP_TOKEN"]
    return [{"type": "url", "url": url, "name": "rube", "authorization_token": token}]


def _is_mutating(tool_name: str) -> bool:
    lowered = tool_name.lower()
    return any(hint in lowered for hint in _MUTATING_HINTS)


def _summarize_input(raw: object) -> str:
    try:
        text = json.dumps(raw, default=str)
    except (TypeError, ValueError):
        text = str(raw)
    if len(text) > _AUDIT_INPUT_CHARS:
        text = text[:_AUDIT_INPUT_CHARS] + "…"
    return text


def _content_to_text(content: object) -> str:
    """mcp_tool_result.content may be a string or a list of content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text is None and isinstance(item, dict):
                text = item.get("text")
            if text:
                parts.append(str(text))
        return " ".join(parts)
    return str(content or "")


def _looks_like_auth_error(text: str) -> bool:
    return bool(_AUTH_ERROR_PATTERN.search(text))


def run_tick(client: Anthropic, policy: Policy, memory: str, is_first_run: bool) -> str:
    """Run one agent tick. Returns the model's end-of-tick summary text."""
    system_blocks = [
        {
            "type": "text",
            "text": static_rules(policy),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": dynamic_context(policy, memory, is_first_run),
        },
    ]

    kwargs: dict = {
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        "max_tokens": _MAX_TOKENS,
        "system": system_blocks,
        "mcp_servers": _mcp_servers(),
        "betas": [_MCP_BETA],
        "messages": [{
            "role": "user",
            "content": "Run your tick now: pull what's new, triage, act, then summarize.",
        }],
    }

    if policy.thinking_budget_tokens > 0:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": policy.thinking_budget_tokens}

    response = client.beta.messages.create(**kwargs)

    summary_parts: list[str] = []
    total_tool_uses = 0
    mutating_tool_uses = 0
    tool_errors = 0
    auth_errors: set[str] = set()
    last_tool_names: dict[str, str] = {}  # tool_use_id -> tool name

    for block in response.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            summary_parts.append(block.text)
        elif btype == "mcp_tool_use":
            total_tool_uses += 1
            name = getattr(block, "name", "?")
            tid = getattr(block, "id", "?")
            last_tool_names[tid] = name
            if _is_mutating(name):
                mutating_tool_uses += 1
            log.info(
                "mcp_tool_use server=%s name=%s input=%s",
                getattr(block, "server_name", "?"),
                name,
                _summarize_input(getattr(block, "input", {})),
            )
        elif btype == "mcp_tool_result":
            is_err = bool(getattr(block, "is_error", False))
            tid = getattr(block, "tool_use_id", "?")
            text = _content_to_text(getattr(block, "content", ""))
            if is_err:
                tool_errors += 1
                if _looks_like_auth_error(text):
                    auth_errors.add(last_tool_names.get(tid, "unknown"))
            log.info(
                "mcp_tool_result tool_use_id=%s is_error=%s body=%s",
                tid,
                is_err,
                text[:_AUDIT_INPUT_CHARS],
            )

    if auth_errors:
        log.error(
            "AUTH_EXPIRED detected for tools: %s — re-authenticate on https://rube.app",
            ", ".join(sorted(auth_errors)),
        )

    if mutating_tool_uses > policy.max_actions_per_tick:
        log.warning(
            "MAX_ACTIONS_PER_TICK exceeded: cap=%d observed_mutating=%d — tighten the cap or inspect the summary.",
            policy.max_actions_per_tick,
            mutating_tool_uses,
        )

    usage = response.usage
    log.info(
        "tick done stop_reason=%s tool_uses=%d mutating=%d errors=%d "
        "input_tokens=%s output_tokens=%s cache_read=%s cache_write=%s",
        response.stop_reason,
        total_tool_uses,
        mutating_tool_uses,
        tool_errors,
        usage.input_tokens,
        usage.output_tokens,
        getattr(usage, "cache_read_input_tokens", 0) or 0,
        getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )
    return "\n".join(summary_parts).strip()
