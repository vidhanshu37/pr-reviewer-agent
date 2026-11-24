import asyncio
import os

from langchain_mcp_adapters.client import MultiServerMCPClient

FILE_PATH = os.environ.get(
    "MCP_TEST_FILE",
    "backend/src/test/java/com/township/backend/complaints/LlmTriageClientTest.java",
)
QUERIES = ("complaint triage LLM client", "REST controller exception handling")


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
    tools = {t.name: t for t in await client.get_tools()}
    print("tools:", sorted(tools))

    diff = text_of(await tools["get_pr_diff"].ainvoke({}))
    print(f"get_pr_diff      chars={len(diff)} | {diff[:90]!r}")

    content = text_of(await tools["get_file_content"].ainvoke({"path": FILE_PATH}))
    print(f"get_file_content chars={len(content)} | {content[:90]!r}")

    for query in QUERIES:
        found = text_of(await tools["search_codebase"].ainvoke({"query": query}))
        print(f"search_codebase  chars={len(found)} | {found[:160]!r}")


asyncio.run(main())