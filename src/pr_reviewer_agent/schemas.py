from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]
Category = Literal["security", "bug", "convention"]


class Finding(BaseModel):
    file: str
    line: int | None = None
    severity: Severity
    category: Category
    message: str
    suggestion: str | None = None
    verdict: Literal["confirmed", "uncertain"] | None = None  # set by the critic; None = not checked


class ReviewRequest(BaseModel):
    job_id: str
    repo: str = Field(description="owner/name")
    pr_number: int
    mcp_token: str


class ReviewResponse(BaseModel):
    job_id: str
    status: Literal["done", "failed"]
    findings: list[Finding] = []
    trace: list[str] = []
    stats: dict = {}
    error: str | None = None