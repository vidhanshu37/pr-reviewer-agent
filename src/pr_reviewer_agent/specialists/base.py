import logging
import re
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, field_validator
from collections.abc import Awaitable, Callable
from pr_reviewer_agent.slicing import DiffSlice, SlicePlan
from pr_reviewer_agent.llm import LLMClient, LLMError, UsageTotals, get_llm
from pr_reviewer_agent.schemas import Category, Finding, Severity

logger = logging.getLogger(__name__)

MAX_RETRIES = 2  # up to 3 LLM calls when the model keeps returning broken JSON
MAX_FINDINGS = 8
FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

class RawFinding(BaseModel):
    """What the model is allowed to say. category is NOT asked from the model: the specialist knows it."""

    file: str
    line: int
    severity: Severity
    message: str
    suggestion: str | None = None

    @field_validator("severity", mode="before")
    @classmethod
    def _normalise_severity(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

class SpecialistOutput(BaseModel):
    findings: list[RawFinding] = []

def parse_output(text: str) -> SpecialistOutput:
    """Tolerate ```json fences and chatter around the JSON; raise ValueError if it is not usable."""
    cleaned = FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in the reply")
    return SpecialistOutput.model_validate_json(cleaned[start:end + 1])  # ValidationError is a ValueError

def is_valid_output(text: str) -> bool:
    try:
        parse_output(text)
        return True
    except ValueError:
        return False



def to_findings(raw: list[RawFinding], category: Category, allowed: dict[str, set[int]]) -> tuple[list[Finding], int]:
    """Keep only findings that point at a line the model could really see; drop the rest (hallucinations)."""
    kept: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()
    for item in raw:
        path = item.file.strip().removeprefix("./")
        key = (path, item.line, item.message[:60])
        if item.line not in allowed.get(path, set()) or key in seen:
            continue
        seen.add(key)
        kept.append(Finding(file=path, line=item.line, severity=item.severity, category=category,
                            message=item.message.strip(), suggestion=item.suggestion))
        if len(kept) == MAX_FINDINGS:
            break
    return kept, len(raw) - len(kept)

def _short(exc: Exception) -> str:
    return " ".join(str(exc).split())[:240]

@dataclass
class BatchOutcome:
    findings: list[Finding] = field(default_factory=list)
    dropped: int = 0
    error: str | None = None
    fatal: bool = False  # LLM itself is failing (quota, bad request): do not hammer it with more batches
    note: str = ""  # extra trace text

async def _review_batch(name: str, category: Category, system_prompt: str, batch: DiffSlice,
                        llm: LLMClient, totals: UsageTotals) -> BatchOutcome:
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=batch.text)]
    for _ in range(MAX_RETRIES + 1):
        try:
            result = await llm.ainvoke(messages, accept=is_valid_output)
        except LLMError as exc:
            return BatchOutcome(error=str(exc), fatal=True)
        totals.add(result)
        try:
            parsed = parse_output(result.content)
        except ValueError as exc:
            logger.warning("%s: invalid model reply (%s): %.300s", name, _short(exc), result.content)
            messages = messages + [
                AIMessage(content=result.content),
                HumanMessage(content=f"Invalid reply ({_short(exc)}). Reply again with ONLY the JSON object."),
            ]
            continue
        findings, dropped = to_findings(parsed.findings, category, batch.added)
        return BatchOutcome(findings=findings, dropped=dropped)
    return BatchOutcome(error=f"model returned invalid JSON {MAX_RETRIES + 1} times")


ReviewFn = Callable[[DiffSlice, LLMClient, UsageTotals], Awaitable[BatchOutcome]]

async def run_specialist(name: str, category: Category, system_prompt: str, plan: SlicePlan, llm: LLMClient | None = None, review: ReviewFn | None = None) -> dict:
    """One specialist = for each batch: LLM -> parse -> validate against the diff. Fails SOFT, reports coverage."""
    if not plan.batches:
        return {"trace": [f"{name}: nothing to review"], "stats": [{"node": name, "skipped": "nothing to review"}]}

    llm = llm or get_llm()
    totals = UsageTotals()
    findings: list[Finding] = []
    dropped = reviewed = ok_batches = 0
    failures: list[str] = []
    truncated = False
    notes: list[str] = []
    if review is None:  # default strategy: plain "diff in, JSON out"
        async def review(batch, llm, totals):
            return await _review_batch(name, category, system_prompt, batch, llm, totals)

    for number, batch in enumerate(plan.batches, start=1):
        outcome = await review(batch, llm, totals)
        if outcome.note:
            notes.append(outcome.note)
        if outcome.error:
            failures.append(f"batch {number}: {outcome.error}")
            if outcome.fatal:
                break  # remaining batches stay unreviewed
            continue
        findings += outcome.findings
        dropped += outcome.dropped
        reviewed += len(batch.included)
        ok_batches += 1
        truncated = truncated or batch.truncated

    if ok_batches == 0:
        return {"trace": [f"{name}: failed ({'; '.join(failures)}); {totals.summary()}"],
                "stats": [{"node": name, "failed": "; ".join(failures), "eligible": plan.eligible, **totals.as_dict()}]}

    note = "; slice truncated" if truncated else ""
    note += "".join(f"; {n}" for n in notes)
    note += f"; failed: {'; '.join(failures)}" if failures else ""
    return {
        "findings": findings,
        "stats": [{"node": name, "findings": len(findings), "dropped": dropped, "reviewed": reviewed,
                   "eligible": plan.eligible, "batches_ok": ok_batches, "batches": len(plan.batches),
                   **({"failed": "; ".join(failures)} if failures else {}), **totals.as_dict()}],
        "trace": [f"{name}: {len(findings)} finding(s), {dropped} dropped; reviewed {reviewed}/{plan.eligible} file(s) "
                  f"in {ok_batches}/{len(plan.batches)} batch(es){note}; {totals.summary()}"],
    }