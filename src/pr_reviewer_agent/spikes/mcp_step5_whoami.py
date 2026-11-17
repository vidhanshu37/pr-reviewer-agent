import asyncio
import os

from langchain_mcp_adapters.client import MultiServerMCPClient

async def main() -> None:
    token = os.environ["MCP_TOKEN"]

    client = MultiServerMCPClient(
        {
            "pr_reviewer": {
                "transport": "streamable_http",
                "url": "http://localhost:8081/mcp",
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    )
    tools = await client.get_tools()
    print("tools:", sorted(t.name for t in tools))

    whoami = next(t for t in tools if t.name == "whoami")
    result = await whoami.ainvoke({})
    print("whoami:", result)

asyncio.run(main())