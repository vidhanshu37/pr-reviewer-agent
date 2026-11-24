from fastapi import FastAPI

from pr_reviewer_agent.graph import review_graph
from pr_reviewer_agent.schemas import ReviewRequest, ReviewResponse

app = FastAPI(title="PR Reviewer Agent")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/review", response_model=ReviewResponse)
async def review(request: ReviewRequest) -> ReviewResponse:
    final = await review_graph.ainvoke(
        {
            "job_id": request.job_id,
            "repo": request.repo,
            "pr_number": request.pr_number,
            "mcp_token": request.mcp_token,
            "findings": [],
            "trace": [],
        }
    )
    error = final.get("error")
    return ReviewResponse(
        job_id=request.job_id,
        status="failed" if error else "done",
        findings=final.get("merged", final.get("findings", [])),
        trace=final.get("trace", []),
        error=error,
    )