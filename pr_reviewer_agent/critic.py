import asyncio
import logging
import re
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from pr_reviewer_agent import config
from pr_reviewer_agent.llm import LLMClient, LLMError, UsageTotals, get_llm
from pr_reviewer_agent.mcp_client import call_tool
from pr_reviewer_agent.prompts import CRITIC_SYSTEM
from pr_reviewer_agent.schemas import Finding
from pr_reviewer_agent.state import ReviewState

logger = logging.getLogger(__name__)

MAX_RETRIES = 1  # up to 2 LLM calls if the first reply is not valid JSON
FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class Verdict(BaseModel):
    id: str
    verdict: Literal["confirmed", "rejected", "uncertain"]
    reason: str = ""


class CriticOutput(BaseModel):
    verdicts: list[Verdict] = []


def parse_verdicts(text: str) -> CriticOutput:
    cleaned = FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in the reply")
    return CriticOutput.model_validate_json(cleaned[start:end + 1])


def is_valid(text: str) -> bool:
    try:
        parse_verdicts(text)
        return True
    except ValueError:
        return False


def make_window(content: str, line: int | None, radius: int, max_chars: int) -> str | None:
    """Numbered lines around `line`, or None when the line is not inside the content we have."""
    lines = content.splitlines()
    if line is None or not 1 <= line <= len(lines):
        return None
    lo, hi = max(line - radius, 1), min(line + radius, len(lines))
    text = "\n".join(f"L{n} {'>>' if n == line else '  '} {lines[n - 1]}" for n in range(lo, hi + 1))
    return text[:max_chars]


async def _fetch_file(token: str, path: str) -> str | None:
    try:
        text = await call_tool(token, "get_file_content", {"path": path})
    except Exception:  # noqa: BLE001 - critic must never break the review
        return None
    return None if text.startswith("ERROR[") else text


async def fetch_files(token: str, findings: list[Finding]) -> dict[str, str | None]:
    paths: list[str] = []
    for f in findings:
        if f.file not in paths:
            paths.append(f.file)
    paths = paths[:config.CRITIC_MAX_FILES]
    contents = await asyncio.gather(*(_fetch_file(token, p) for p in paths))  # all files in parallel
    return dict(zip(paths, contents))


def build_prompt(findings: list[Finding], windows: list[str | None]) -> str:
    blocks = []
    for number, (f, window) in enumerate(zip(findings, windows), start=1):
        blocks.append(f"### F{number}: {f.file} line {f.line} [{f.category}/{f.severity}]\n"
                      f"Finding: {f.message}\n"
                      f"Code window:\n{window if window else '(not available)'}")
    return "\n\n".join(blocks)


async def judge(findings: list[Finding], windows: list[str | None], llm: LLMClient,
                totals: UsageTotals) -> dict[str, Verdict]:
    messages = [SystemMessage(content=CRITIC_SYSTEM), HumanMessage(content=build_prompt(findings, windows))]
    for _ in range(MAX_RETRIES + 1):
        result = await llm.ainvoke(messages, accept=is_valid)  # LLMError propagates to the caller (fail-open)
        totals.add(result)
        try:
            return {v.id: v for v in parse_verdicts(result.content).verdicts}
        except ValueError as exc:
            logger.warning("critic: invalid model reply (%s): %.300s", " ".join(str(exc).split())[:200], result.content)
            messages = messages + [AIMessage(content=result.content),
                                   HumanMessage(content="Invalid reply. Reply again with ONLY the JSON object.")]
    raise LLMError("critic returned invalid JSON")


def apply_verdicts(findings: list[Finding], windows: list[str | None], verdicts: dict[str, Verdict]
                   ) -> tuple[list[Finding], list[dict], dict[str, int]]:
    """Code (not the model) decides. Confirm/reject both need a visible window; a rejection also needs a reason."""
    kept: list[Finding] = []
    rejected: list[Finding] = []
    counts = {"confirmed": 0, "uncertain": 0, "rejected": 0}
    for number, (f, window) in enumerate(zip(findings, windows), start=1):
        v = verdicts.get(f"F{number}")
        verdict = v.verdict if v else "uncertain"
        if window is None or (verdict == "rejected" and not v.reason.strip()):
            verdict = "uncertain"  # no visible code (or no evidence) -> never confirm, never reject
        counts[verdict] += 1
        if verdict == "rejected":
            rejected.append({"file": f.file, "line": f.line, "category": f.category, "severity": f.severity, "message": f.message, "reason": v.reason.strip()})
        else:
            kept.append(f.model_copy(update={"verdict": verdict}))
    return kept, rejected, counts


async def run_critic(token: str, merged: list[Finding], llm: LLMClient | None = None) -> dict:
    if not merged:
        return {"trace": ["critic: nothing to verify"], "stats": [{"node": "critic", "skipped": "nothing to verify"}]}
    judged, unjudged = merged[:config.CRITIC_MAX_FINDINGS], merged[config.CRITIC_MAX_FINDINGS:]
    totals = UsageTotals()
    try:
        files = await fetch_files(token, judged)
        windows = [make_window(files[f.file], f.line, config.CRITIC_WINDOW_LINES, config.CRITIC_WINDOW_CHARS)
                   if files.get(f.file) else None for f in judged]
        if not any(windows):
            reason = f"no file content available for {len(judged)} finding(s)"
            return {"trace": [f"critic: skipped ({reason})"], "stats": [{"node": "critic", "failed": reason}]}
        verdicts = await judge(judged, windows, llm or get_llm(), totals)
    except LLMError as exc:
        return {"trace": [f"critic: skipped ({exc}); {totals.summary()}"],
                "stats": [{"node": "critic", "failed": str(exc), **totals.as_dict()}]}
    except Exception as exc:  # noqa: BLE001 - fail open, type only
        return {"trace": [f"critic: skipped ({type(exc).__name__})"],
                "stats": [{"node": "critic", "failed": type(exc).__name__}]}

    kept, rejected, counts = apply_verdicts(judged, windows, verdicts)
    extra = f"; {len(unjudged)} not checked" if unjudged else ""
    return {
        "merged": kept + unjudged,
        "rejected": rejected,
        "stats": [{"node": "critic", "confirmed": counts["confirmed"], "uncertain": counts["uncertain"],
                   "rejected": counts["rejected"], "not_checked": len(unjudged), **totals.as_dict()}],
        "trace": [f"critic: {counts['confirmed']} confirmed, {counts['uncertain']} uncertain, "
                  f"{counts['rejected']} rejected{extra}; {totals.summary()}"],
    }


async def critic_node(state: ReviewState) -> dict:
    return await run_critic(state["mcp_token"], state.get("merged", []))