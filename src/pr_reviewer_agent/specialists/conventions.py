import logging

from langchain_core.messages import HumanMessage, SystemMessage

from pr_reviewer_agent import config
from pr_reviewer_agent.llm import LLMClient, LLMError, ToolCallError, UsageTotals
from pr_reviewer_agent.mcp_client import call_tool
from pr_reviewer_agent.prompts import CONVENTIONS_SYSTEM
from pr_reviewer_agent.slicing import DiffSlice, build_plan
from pr_reviewer_agent.specialists.base import (BatchOutcome, _review_batch, is_valid_output, parse_output,
                                                run_specialist, to_findings)
from pr_reviewer_agent.state import ReviewState
from pr_reviewer_agent.triage import conventions_score

logger = logging.getLogger(__name__)

# Tool schema the model sees. The REAL tool lives on the Spring MCP server; we execute it ourselves.
SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_codebase",
        "description": "Semantic search over the indexed code of this repository. Returns relevant code chunks.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Short description of the pattern to look for"}},
            "required": ["query"],
        },
    },
}


def _queries(tool_calls: list[dict], limit: int) -> list[str]:
    seen: list[str] = []
    for call in tool_calls:
        query = call.get("args", {}).get("query") if call.get("name") == "search_codebase" else None
        if isinstance(query, str) and query.strip() and query.strip() not in seen:
            seen.append(query.strip()[:300])
    return seen[:limit]


async def _search(token: str, query: str) -> str:
    try:
        text = await call_tool(token, "search_codebase", {"query": query})
    except Exception as exc:  # noqa: BLE001 - a failed search must never kill the review
        return f"(search failed: {type(exc).__name__})"
    return text[:config.CONVENTIONS_RESULT_CHARS]


def make_review(token: str, name: str = "conventions"):
    async def review(batch: DiffSlice, llm: LLMClient, totals: UsageTotals) -> BatchOutcome:
        messages = [SystemMessage(content=CONVENTIONS_SYSTEM), HumanMessage(content=batch.text)]

        # Turn 1: let the model decide whether it wants to search the repo.
        try:
            first = await llm.ainvoke(messages, tools=[SEARCH_TOOL])
        except ToolCallError:
            logger.warning("%s: malformed tool call, answering without repo context", name)
            outcome = await _review_batch(name, "convention", CONVENTIONS_SYSTEM, batch, llm, totals)
            outcome.note = "0 repo search(es) (tool call failed)"
            return outcome
        except LLMError as exc:
            return BatchOutcome(error=str(exc), fatal=True)
        totals.add(first)

        queries = _queries(first.tool_calls, config.CONVENTIONS_MAX_SEARCHES)
        if not queries:
            if is_valid_output(first.content):  # model answered directly, no tools needed
                findings, dropped = to_findings(parse_output(first.content).findings, "convention", batch.added)
                return BatchOutcome(findings=findings, dropped=dropped, note="0 repo search(es)")
            outcome = await _review_batch(name, "convention", CONVENTIONS_SYSTEM, batch, llm, totals)
            outcome.note = "0 repo search(es)"
            return outcome

        # We are the tool executor: run the searches, then collapse everything into ONE plain message.
        blocks = [f'#### search_codebase("{q}")\n{await _search(token, q)}' for q in queries]
        context = "\n\n".join(blocks)
        text = (f"{batch.text}\n\n### Repository context (search results)\n{context}\n\n"
                "Now reply with ONLY the JSON object.")
        enriched = DiffSlice(text=text, added=batch.added, included=batch.included, truncated=batch.truncated)
        outcome = await _review_batch(name, "convention", CONVENTIONS_SYSTEM, enriched, llm, totals)
        outcome.note = f"{len(queries)} repo search(es)"
        return outcome

    return review


async def conventions_node(state: ReviewState) -> dict:
    plan = build_plan(state.get("files", {}), conventions_score, config.CONVENTIONS_SLICE_TOKENS, 1)
    return await run_specialist("conventions", "convention", CONVENTIONS_SYSTEM, plan, review=make_review(state["mcp_token"]))