import asyncio
import os
import time

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
    print("tools:", [t.name for t in tools])

    ping = next(t for t in tools if t.name == "ping")
    started = time.perf_counter()
    result = await ping.ainvoke({"message": "hello with token"})
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"ping: {elapsed_ms:.0f} ms | result={result!r}")


asyncio.run(main())