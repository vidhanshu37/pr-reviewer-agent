from langgraph.graph import END, StateGraph
from pr_reviewer_agent.specialists.security import security_node
from pr_reviewer_agent.diff_utils import parse_diff
from pr_reviewer_agent.mcp_client import call_tool
from pr_reviewer_agent.state import ReviewState
from pr_reviewer_agent.triage import select_specialists, ORDER
from pr_reviewer_agent.merge import merge_findings
from pr_reviewer_agent.specialists.bugs import bugs_node
from pr_reviewer_agent.specialists.conventions import conventions_node
from pr_reviewer_agent.critic import critic_node
import inspect
import time

def timed(name: str, node):
    """Wrap a node: measure wall time and make sure it contributes exactly one stats entry."""
    async def wrapper(state: ReviewState) -> dict:
        started = time.monotonic()
        result = node(state)
        if inspect.isawaitable(result):
            result = await result
        entries = result.get("stats") or [{"node": name}]
        entries[0]["wall_s"] = round(time.monotonic() - started, 2)
        return {**result, "stats": entries}
    return wrapper

def _reason(exec: BaseException) -> str:
    # MCP client wraps real errors in ExceptionGroup; dig out the first leaf.
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}"

async def fetch(state: ReviewState) -> dict:
    try:
        diff = await call_tool(state["mcp_token"], "get_full_pr_diff")
    except Exception as exc:
        return {"error": f"fetch failed: {_reason(exc)}", "trace": ["fetch: failed"]}

    if diff.startswith("ERROR["):
        return {"error": f"fetch failed: {diff.split(']')[0][6:]}", "trace": ["fetch: tool error"]}

    files = parse_diff(diff)
    return {"diff": diff, "files": files, "trace": [f"fetch: {len(files)} file(s), {len(diff)} chars"]}


def triage(state: ReviewState) -> dict:
    selected = select_specialists(state.get("files", {}))
    label = ", ".join(selected) if selected else "none (nothing reviewable)"
    return {"selected": selected, "trace": [f"triage: {label}"]}

def _stub(name: str):
    def node(state: ReviewState) -> dict:
        return {"trace": [f"{name}: stub (no LLM yet)"]}
    return node

def merge(state: ReviewState) -> dict:
    merged, duplicates = merge_findings(state.get("findings", []))
    return {"merged": merged, "trace": [f"merge: {len(merged)} finding(s), {duplicates} duplicate(s) dropped"]}

def _next_after(current: str | None):
    """Router: go to the next selected specialist after `current`, else to merge."""
    start = 0 if current is None else ORDER.index(current) + 1

    def route(state: ReviewState) -> str:
        selected = state.get("selected", [])
        for name in ORDER[start:]:
            if name in selected:
                return name
        return "merge"

    return route

def _targets_after(current: str | None) -> list[str]:
    start = 0 if current is None else ORDER.index(current) + 1
    return [*ORDER[start:], "merge"]

def build_graph():
    g = StateGraph(ReviewState)
    g.add_node("fetch", timed("fetch", fetch))
    g.add_node("triage", timed("triage", triage))
    g.add_node("merge", timed("merge", merge))
    g.add_node("critic", timed("critic", critic_node))
    real_nodes = {"security": security_node, "bugs": bugs_node, "conventions": conventions_node}
    for name in ORDER:
        g.add_node(name, timed(name, real_nodes.get(name, _stub(name))))   # specialists wale loop mein

    g.set_entry_point("fetch")
    g.add_conditional_edges("fetch", lambda s: "end" if s.get("error") else "triage",
                            {"triage": "triage", "end": END})

    targets = {**{name: name for name in ORDER}, "merge": "merge", "end": END}

    g.add_conditional_edges("triage", _next_after(None), _targets_after(None))
    for name in ORDER:
        g.add_conditional_edges(name, _next_after(name), _targets_after(name))
    g.add_edge("merge", "critic")
    g.add_edge("critic", END)

    return g.compile()

review_graph = build_graph()




