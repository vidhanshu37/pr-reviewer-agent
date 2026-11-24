import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, field_validator

from pr_reviewer_agent.llm import LLMClient, LLMError, UsageTotals, get_llm
from pr_reviewer_agent.schemas import Category, Finding, Severity
from pr_reviewer_agent.slicing import DiffSlice

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


async def run_specialist(name: str, category: Category, system_prompt: str, diff_slice: DiffSlice,
                         llm: LLMClient | None = None) -> dict:
    """One specialist = slice -> LLM -> parse -> validate against the diff. Fails SOFT: never kills the review."""
    if not diff_slice.included:
        return {"trace": [f"{name}: nothing to review"]}

    llm = llm or get_llm()
    totals = UsageTotals()
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=diff_slice.text)]
    parsed: SpecialistOutput | None = None

    for _ in range(MAX_RETRIES + 1):
        try:
            result = await llm.ainvoke(messages, accept=is_valid_output)
        except LLMError as exc:
            return {"trace": [f"{name}: failed ({exc}); {totals.summary()}"]}
        totals.add(result)
        try:
            parsed = parse_output(result.content)
            break
        except ValueError as exc:
            logger.warning("%s: invalid model reply (%s): %.300s", name, _short(exc), result.content)
            messages = messages + [
                AIMessage(content=result.content),
                HumanMessage(content=f"Invalid reply ({_short(exc)}). Reply again with ONLY the JSON object."),
            ]

    if parsed is None:
        return {"trace": [f"{name}: failed (model returned invalid JSON {MAX_RETRIES + 1} times); {totals.summary()}"]}

    findings, dropped = to_findings(parsed.findings, category, diff_slice.added)
    note = f", {len(diff_slice.skipped)} file(s) skipped for budget" if diff_slice.skipped else ""
    note += ", slice truncated" if diff_slice.truncated else ""
    return {
        "findings": findings,
        "trace": [f"{name}: {len(findings)} finding(s), {dropped} dropped, "
                  f"{len(diff_slice.included)} file(s) sent{note}; {totals.summary()}"],
    }