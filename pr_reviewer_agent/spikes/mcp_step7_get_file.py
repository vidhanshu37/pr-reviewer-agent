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
    get_file = next(t for t in tools if t.name == "get_file_content")

    cases = {
        "existing": "backend/src/test/java/com/township/backend/complaints/LlmTriageClientTest.java",
        "missing": "does/not/exist.txt",
        "invalid": "../secret.txt",
    }
    for label, path in cases.items():
        text = text_of(await get_file.ainvoke({"path": path}))
        print(f"[{label}] chars={len(text)} | {text[:160]!r}")


asyncio.run(main())