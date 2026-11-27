from fastapi import FastAPI

from pr_reviewer_agent.graph import review_graph
from pr_reviewer_agent.schemas import ReviewRequest, ReviewResponse
import time
from pr_reviewer_agent.stats import build_stats
from pr_reviewer_agent.stats import build_stats, compute_status

app = FastAPI(title="PR Reviewer Agent")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/review", response_model=ReviewResponse)
async def review(request: ReviewRequest) -> ReviewResponse:
    started = time.monotonic()

    final = await review_graph.ainvoke(
        {
            "trace": [],
            "stats": [],
            "job_id": request.job_id,
            "repo": request.repo,
            "pr_number": request.pr_number,
            "mcp_token": request.mcp_token,
            "findings": [],
        }
    )

    error = final.get("error")
    entries = final.get("stats", [])
    status, warnings = compute_status(error, entries)
    return ReviewResponse(
        job_id=request.job_id,
        status=status,
        warnings=warnings,
        findings=final.get("merged", final.get("findings", [])),
        trace=final.get("trace", []),
        stats=build_stats(entries, time.monotonic() - started, final.get("rejected", [])),
        error=error,
    )