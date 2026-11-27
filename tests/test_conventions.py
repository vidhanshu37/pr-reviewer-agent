import json

import groq
import pytest

from pr_reviewer_agent import config
from pr_reviewer_agent.slicing import build_plan
from pr_reviewer_agent.specialists import conventions as conv
from pr_reviewer_agent.triage import conventions_score
from tests.helpers import ai, status_err, tool_ai

pytestmark = pytest.mark.anyio
FILES = {"A.java": "@@ -1,1 +1,3 @@\n+class A {}\n+int x = 1;\n+int y = 2;", "R.md": "@@ -1 +1 @@\n+x"}
PLAN = build_plan(FILES, conventions_score, 2500, 1)
LINE = min(PLAN.batches[0].added["A.java"])
ANSWER = json.dumps({"findings": [{"file": "A.java", "line": LINE, "severity": "low", "message": "m"}]})


@pytest.fixture
def searches(monkeypatch):
    calls = []

    async def fake_call(token, name, args=None):
        calls.append((token, name, args))
        return "### Result 1: B.java\n" + "x" * 5000
    monkeypatch.setattr(conv, "call_tool", fake_call)
    return calls


async def run(llm):
    return await conv.run_specialist("conventions", "convention", "SYS", PLAN, llm, review=conv.make_review("TOK"))


async def test_searches_are_deduped_capped_and_results_injected(make_llm, searches):
    llm, chat, _ = make_llm([tool_ai("error handling", "error handling", "logging", "dto", "naming"), ai(ANSWER)])
    r = await run(llm)
    final_text = chat.seen[1][1].content
    assert len(searches) == 3 and searches[0][0] == "TOK" and chat.calls == 2
    assert "Repository context" in final_text and 'search_codebase("logging")' in final_text
    assert "x" * (config.CONVENTIONS_RESULT_CHARS + 1) not in final_text      # result truncated
    assert chat.seen[1][1].type == "human"                                    # final call is plain text, no tool messages
    assert r["findings"][0].category == "convention" and "3 repo search(es)" in r["trace"][0]
    assert chat.bound[0]["function"]["name"] == "search_codebase"


async def test_direct_answer_needs_no_search(make_llm, searches):
    llm, chat, _ = make_llm([ai(ANSWER)])
    r = await run(llm)
    assert chat.calls == 1 and not searches and len(r["findings"]) == 1 and "0 repo search(es)" in r["trace"][0]


async def test_failed_search_does_not_kill_the_review(make_llm, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(conv, "call_tool", boom)
    llm, chat, _ = make_llm([tool_ai("q"), ai(ANSWER)])
    r = await run(llm)
    assert len(r["findings"]) == 1 and "search failed: RuntimeError" in chat.seen[1][1].content


async def test_malformed_tool_call_falls_back_to_plain_answer(make_llm, searches):
    bad = status_err(groq.BadRequestError, 400, body={"error": {"code": "tool_use_failed"}})
    bad.args = ("tool_use_failed",)
    llm, chat, _ = make_llm([bad, ai(ANSWER)])
    r = await run(llm)
    assert chat.calls == 2 and len(r["findings"]) == 1 and "tool call failed" in r["trace"][0]


async def test_other_400_is_fatal(make_llm, searches):
    llm, _, _ = make_llm([status_err(groq.BadRequestError, 400)])
    r = await run(llm)
    assert "findings" not in r and "failed" in r["stats"][0]


async def test_invalid_json_after_search_is_retried(make_llm, searches):
    llm, chat, _ = make_llm([tool_ai("q"), ai("oops"), ai(ANSWER)])
    assert len((await run(llm))["findings"]) == 1 and chat.calls == 3
