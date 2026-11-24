import asyncio
import os

from langchain_mcp_adapters.client import MultiServerMCPClient

def text_of(result) -> str:
    if isinstance(result, list):
        return "".join(block.get("text", "") for block in result if isinstance(block, dict))
    return str(result)


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

    get_pr_diff = next(t for t in tools if t.name == "get_pr_diff")
    result = await get_pr_diff.ainvoke({})
    text = text_of(result)

    if text.startswith("ERROR["):
        print("TOOL ERROR:", text)
        return

    print("chars:", len(text))
    print("--- first 700 chars ---")
    print(text[:700])


asyncio.run(main())