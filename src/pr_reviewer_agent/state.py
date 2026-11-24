import operator
from typing import Annotated, TypedDict

from pr_reviewer_agent.schemas import Finding


class ReviewState(TypedDict, total=False) :
    # inputs (set once by /review)
    job_id: str
    repo: str
    pr_number: int
    mcp_token: str
    # produced by nodes
    diff: str
    files: dict[str, str]
    selected: list[str]
    error: str | None
    # reducers: every node ADDS to these, nobody overwrites them
    findings: Annotated[list[Finding], operator.add]
    trace: Annotated[list[str], operator.add]
    merged: list[Finding]
