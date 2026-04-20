"""Claude Agents SDK + Composio example."""

import asyncio

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, create_sdk_mcp_server
from composio import Composio
from composio_claude_agent_sdk import ClaudeAgentSDKProvider

composio = Composio(provider=ClaudeAgentSDKProvider())
user_id = "user_ck79rp"

session = composio.create(user_id=user_id)
tools = session.tools()
custom_server = create_sdk_mcp_server(name="composio", version="1.0.0", tools=tools)


async def main():
    options = ClaudeAgentOptions(
        system_prompt="You are a helpful assistant",
        permission_mode="bypassPermissions",
        mcp_servers={
            "composio": custom_server,
        },
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Star the composiohq/composio repo on GitHub")
        async for msg in client.receive_response():
            print(msg)


if __name__ == "__main__":
    asyncio.run(main())
