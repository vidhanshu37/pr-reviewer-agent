from langchain_mcp_adapters.client import MultiServerMCPClient

from pr_reviewer_agent.config import MCP_URL


def build_client(token: str) -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {
            "pr_reviewer": {
                "transport": "streamable_http",
                "url": MCP_URL,
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    )

def text_of(result) -> str:
    if isinstance(result, list):
        return "".join(block.get("text", "") for block in result if isinstance(block, dict))
    return str(result)


async def call_tool(token: str, name: str, arguments: dict | None = None) -> str:
    tools = {tool.name: tool for tool in await build_client(token).get_tools()}
    if name not in tools:
        raise RuntimeError(f"MCP tool not available: {name}")
    return text_of(await tools[name].ainvoke(arguments or {}))


async def list_tool_names(token: str) -> list[str]:
    tools = await build_client(token).get_tools()
    return sorted(tool.name for tool in tools)