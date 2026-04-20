"""Single-tick agent run: one Claude call with Rube MCP wired in.

We use Anthropic's MCP connector so Claude can discover and invoke Rube's
tools directly — no manual tool-schema plumbing in this file. The model
loops through tool_use / mcp_tool_result turns on the server side until it
emits a final text block; we return that text as the tick summary.
"""
from __future__ import annotations

import logging
import os

from anthropic import Anthropic

from policy import Policy
from prompts import system_prompt

log = logging.getLogger("agent")

_MCP_BETA = "mcp-client-2025-04-04"
_MAX_TOKENS = 8192


def _mcp_servers() -> list[dict]:
    url = os.environ["RUBE_MCP_URL"]
    token = os.environ.get("RUBE_MCP_TOKEN", "")
    server: dict = {"type": "url", "url": url, "name": "rube"}
    if token:
        server["authorization_token"] = token
    return [server]


def run_tick(client: Anthropic, policy: Policy, last_summary: str) -> str:
    """Run one agent tick. Returns the model's end-of-tick summary text."""
    response = client.beta.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        max_tokens=_MAX_TOKENS,
        system=system_prompt(policy, last_summary),
        mcp_servers=_mcp_servers(),
        betas=[_MCP_BETA],
        messages=[{
            "role": "user",
            "content": "Run your tick now: pull what's new, triage, act, then summarize.",
        }],
    )

    summary_parts: list[str] = []
    mcp_calls = 0
    for block in response.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            summary_parts.append(block.text)
        elif btype == "mcp_tool_use":
            mcp_calls += 1
            log.info("mcp_tool_use name=%s server=%s", block.name, block.server_name)
        elif btype == "mcp_tool_result":
            is_err = getattr(block, "is_error", False)
            log.info("mcp_tool_result tool_use_id=%s is_error=%s", block.tool_use_id, is_err)

    log.info(
        "tick done stop_reason=%s mcp_calls=%d input_tokens=%s output_tokens=%s",
        response.stop_reason,
        mcp_calls,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    return "\n".join(summary_parts).strip()
