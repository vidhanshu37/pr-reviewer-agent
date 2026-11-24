from pr_reviewer_agent import config
from pr_reviewer_agent.prompts import BUGS_SYSTEM
from pr_reviewer_agent.slicing import build_plan
from pr_reviewer_agent.specialists.base import run_specialist
from pr_reviewer_agent.state import ReviewState
from pr_reviewer_agent.triage import bugs_score


async def bugs_node(state: ReviewState) -> dict:
    plan = build_plan(state.get("files", {}), bugs_score, config.SPECIALIST_SLICE_TOKENS, config.SPECIALIST_MAX_BATCHES)
    return await run_specialist("bugs", "bug", BUGS_SYSTEM, plan)