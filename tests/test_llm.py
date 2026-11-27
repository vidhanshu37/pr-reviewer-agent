import os

import groq
import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from pr_reviewer_agent.llm import DiskCache, LLMError, ToolCallError, UsageTotals
from tests.helpers import ai, status_err

MSG = [SystemMessage("be brief"), HumanMessage("review this diff")]
pytestmark = pytest.mark.anyio


async def test_basic_call_extracts_usage(make_llm):
    llm, _, _ = make_llm([ai("hello")])
    r = await llm.ainvoke(MSG)
    assert (r.content, r.usage.total_tokens, r.usage.reasoning_tokens, r.attempts) == ("hello", 150, 20, 1)


async def test_cache_hit_miss_and_survives_restart(make_llm, tmp_path):
    llm, chat, _ = make_llm([ai("A"), ai("B")], use_cache=True, cache=DiskCache(tmp_path))
    await llm.ainvoke(MSG)
    second = await llm.ainvoke(MSG)
    third = await llm.ainvoke([HumanMessage("other prompt")])
    assert chat.calls == 2 and second.cached and second.usage.total_tokens == 0 and not third.cached
    llm2, chat2, _ = make_llm([ai("never")], use_cache=True, cache=DiskCache(tmp_path))  # "new process"
    assert (await llm2.ainvoke(MSG)).cached and chat2.calls == 0


async def test_429_honours_retry_after(make_llm):
    llm, _, clock = make_llm([status_err(groq.RateLimitError, 429, {"retry-after": "7"}), ai("ok")])
    r = await llm.ainvoke(MSG)
    assert r.attempts == 2 and 7.0 in clock.sleeps and r.usage.waited_s >= 7


async def test_5xx_uses_exponential_backoff(make_llm):
    llm, _, clock = make_llm([status_err(groq.InternalServerError, 500), status_err(groq.InternalServerError, 502), ai("ok")])
    r = await llm.ainvoke(MSG)
    assert r.attempts == 3 and 2.0 <= clock.sleeps[0] < 3 and 4.0 <= clock.sleeps[1] < 5


async def test_connection_error_is_retried(make_llm):
    from tests.helpers import REQ
    llm, _, _ = make_llm([groq.APIConnectionError(request=REQ), ai("ok")])
    assert (await llm.ainvoke(MSG)).attempts == 2


async def test_400_is_not_retried_and_leaks_no_body(make_llm):
    llm, chat, _ = make_llm([status_err(groq.BadRequestError, 400)])
    with pytest.raises(LLMError) as exc:
        await llm.ainvoke(MSG)
    assert chat.calls == 1 and "400" in str(exc.value) and "boom" not in str(exc.value)


async def test_retries_exhausted(make_llm):
    llm, chat, _ = make_llm([status_err(groq.RateLimitError, 429)] * 4, max_attempts=4)
    with pytest.raises(LLMError, match="rate_limited"):
        await llm.ainvoke(MSG)
    assert chat.calls == 4


async def test_empty_answer_raises_and_is_not_cached(make_llm, tmp_path):
    llm, _, _ = make_llm([ai("   ")], use_cache=True, cache=DiskCache(tmp_path))
    with pytest.raises(LLMError, match="empty"):
        await llm.ainvoke(MSG)
    assert not os.listdir(tmp_path)


async def test_pacing_waits_only_when_window_is_full(make_llm):
    llm, _, _ = make_llm([ai("1", 800, 200), ai("2", 800, 200), ai("3", 800, 200)], tpm_limit=3000)
    r1 = await llm.ainvoke([HumanMessage("a" * 400)])
    r2 = await llm.ainvoke([HumanMessage("b" * 400)])
    r3 = await llm.ainvoke([HumanMessage("c" * 400)])
    assert r1.usage.waited_s == 0 and r2.usage.waited_s == 0 and 55 <= r3.usage.waited_s <= 61
    totals = UsageTotals()
    for r in (r1, r2, r3):
        totals.add(r)
    assert totals.calls == 3 and totals.total_tokens == 3000


async def test_malformed_tool_call_becomes_tool_call_error(make_llm):
    bad = status_err(groq.BadRequestError, 400, body={"error": {"code": "tool_use_failed"}})
    bad.args = ("Failed to call a function tool_use_failed",)
    llm, _, _ = make_llm([bad])
    tools = [{"type": "function", "function": {"name": "search_codebase", "parameters": {"type": "object"}}}]
    with pytest.raises(ToolCallError):
        await llm.ainvoke(MSG, tools=tools)
