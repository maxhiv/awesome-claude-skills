"""Single-tick agent run: one Claude call with Rube MCP wired in.

We use Anthropic's MCP connector so Claude can discover and invoke Rube's
tools directly — no manual tool-schema plumbing in this file. The model
loops through tool_use / mcp_tool_result turns on the server side until it
emits a final text block; we return that text as the tick summary.
"""
from __future__ import annotations

import json
import logging
import os

from anthropic import Anthropic

from policy import Policy
from prompts import system_prompt

log = logging.getLogger("agent")

_MCP_BETA = "mcp-client-2025-04-04"
_MAX_TOKENS = 8192
_AUDIT_INPUT_CHARS = 240  # truncate tool_use inputs in the audit log

# Mutating tool names we care about when warning about cap overruns.
_MUTATING_HINTS = (
    "send", "reply", "forward", "create", "update", "delete", "archive",
    "trash", "accept", "decline", "post", "move", "insert",
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


def run_tick(client: Anthropic, policy: Policy, memory: str, is_first_run: bool) -> str:
    """Run one agent tick. Returns the model's end-of-tick summary text."""
    response = client.beta.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        max_tokens=_MAX_TOKENS,
        system=system_prompt(policy, memory, is_first_run),
        mcp_servers=_mcp_servers(),
        betas=[_MCP_BETA],
        messages=[{
            "role": "user",
            "content": "Run your tick now: pull what's new, triage, act, then summarize.",
        }],
    )

    summary_parts: list[str] = []
    total_tool_uses = 0
    mutating_tool_uses = 0
    tool_errors = 0

    for block in response.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            summary_parts.append(block.text)
        elif btype == "mcp_tool_use":
            total_tool_uses += 1
            name = getattr(block, "name", "?")
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
            if is_err:
                tool_errors += 1
            log.info(
                "mcp_tool_result tool_use_id=%s is_error=%s",
                getattr(block, "tool_use_id", "?"),
                is_err,
            )

    if mutating_tool_uses > policy.max_actions_per_tick:
        log.warning(
            "MAX_ACTIONS_PER_TICK exceeded: cap=%d observed_mutating=%d — tighten the cap or inspect the summary.",
            policy.max_actions_per_tick,
            mutating_tool_uses,
        )

    log.info(
        "tick done stop_reason=%s tool_uses=%d mutating=%d errors=%d input_tokens=%s output_tokens=%s",
        response.stop_reason,
        total_tool_uses,
        mutating_tool_uses,
        tool_errors,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    return "\n".join(summary_parts).strip()
