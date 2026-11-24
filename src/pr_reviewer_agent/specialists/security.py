from pr_reviewer_agent import config
from pr_reviewer_agent.prompts import SECURITY_SYSTEM
from pr_reviewer_agent.slicing import build_slice
from pr_reviewer_agent.specialists.base import run_specialist
from pr_reviewer_agent.state import ReviewState
from pr_reviewer_agent.triage import security_score


async def security_node(state: ReviewState) -> dict:
    diff_slice = build_slice(state.get("files", {}), security_score, config.SPECIALIST_SLICE_TOKENS)
    return await run_specialist("security", "security", SECURITY_SYSTEM, diff_slice)