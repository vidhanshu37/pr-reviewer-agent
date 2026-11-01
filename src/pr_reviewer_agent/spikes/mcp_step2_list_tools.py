import asyncio
import time

from langchain_mcp_adapters.client import MultiServerMCPClient

async def main() -> None:
    client = MultiServerMCPClient(
        {
            "pr_reviewer": {
                "transport": "streamable_http",
                "url": "http://localhost:8081/mcp",
            }
        }
    )
    tools = await client.get_tools()
    ping = next(t for t in tools if t.name == "ping")

    for i in range(3):
        started = time.perf_counter()
        result = await ping.ainvoke({"message": f"hello {i}"})
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"call {i}: {elapsed_ms:.0f} ms | type={type(result).__name__} | result={result!r}")


asyncio.run(main())