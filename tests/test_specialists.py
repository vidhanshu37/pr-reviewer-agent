import json
import os

import groq
import pytest

from pr_reviewer_agent.llm import DiskCache
from pr_reviewer_agent.slicing import build_plan
from pr_reviewer_agent.specialists.base import RawFinding, parse_output, run_specialist, to_findings
from pr_reviewer_agent.triage import security_score
from tests.helpers import ai, status_err
from tests.test_pipeline_parts import PATCH

pytestmark = pytest.mark.anyio
PLAN = build_plan({"src/AuthController.java": PATCH}, security_score, 3000, 2)
ONE = json.dumps({"findings": [{"file": "src/AuthController.java", "line": 11, "severity": "critical",
                                "message": "SQL built by concatenation", "suggestion": "use PreparedStatement"}]})
GOOD = '{"findings":[{"file":"a.java","line":3,"severity":"High","message":"m","suggestion":"s"}]}'


def test_parse_accepts_fences_and_chatter_and_normalises_severity():
    assert parse_output(GOOD).findings[0].severity == "high"
    assert len(parse_output("Sure!\n```json\n" + GOOD + "\n```\nHope it helps").findings) == 1


@pytest.mark.parametrize("bad", [
    "no json here", "{broken",
    '{"findings":[{"file":"a","line":"x","severity":"high","message":"m"}]}',
    '{"findings":[{"file":"a","line":1,"severity":"urgent","message":"m"}]}'])
def test_parse_rejects_bad_replies_with_value_error(bad):
    with pytest.raises(ValueError):
        parse_output(bad)


def test_to_findings_drops_hallucinated_lines_files_and_duplicates():
    raw = [RawFinding(file="src/AuthController.java", line=11, severity="high", message="sql injection here"),
           RawFinding(file="src/AuthController.java", line=11, severity="high", message="sql injection here"),
           RawFinding(file="src/AuthController.java", line=999, severity="low", message="made up line"),
           RawFinding(file="src/Nope.java", line=1, severity="low", message="made up file"),
           RawFinding(file="./src/AuthController.java", line=12, severity="medium", message="token in log")]
    kept, dropped = to_findings(raw, "security", {"src/AuthController.java": {11, 12}})
    assert [f.line for f in kept] == [11, 12] and dropped == 3 and all(f.category == "security" for f in kept)


async def test_happy_path(make_llm):
    llm, chat, _ = make_llm([ai(ONE)])
    r = await run_specialist("security", "security", "SYS", PLAN, llm)
    assert len(r["findings"]) == 1 and chat.calls == 1
    assert "reviewed 1/1 file(s) in 1/1 batch(es)" in r["trace"][0]
    assert r["stats"][0]["findings"] == 1 and "failed" not in r["stats"][0]


async def test_bad_json_is_retried_with_feedback(make_llm):
    llm, chat, _ = make_llm([ai("I think there is an issue"), ai(ONE)])
    r = await run_specialist("security", "security", "SYS", PLAN, llm)
    assert len(r["findings"]) == 1 and [len(m) for m in chat.seen] == [2, 4]


async def test_bad_json_three_times_fails_soft_and_reports_it(make_llm):
    llm, chat, _ = make_llm([ai("nope"), ai("still nope"), ai("{bad")])
    r = await run_specialist("security", "security", "SYS", PLAN, llm)
    assert "findings" not in r and chat.calls == 3 and "invalid JSON" in r["stats"][0]["failed"]


async def test_llm_400_fails_soft_with_failed_stat(make_llm):
    llm, _, _ = make_llm([status_err(groq.BadRequestError, 400)])
    r = await run_specialist("security", "security", "SYS", PLAN, llm)
    assert "findings" not in r and "HTTP 400" in r["stats"][0]["failed"]


async def test_nothing_to_review_makes_zero_llm_calls(make_llm):
    llm, chat, _ = make_llm([])
    plan = build_plan({"README.md": "@@ -1 +1 @@\n+x"}, security_score, 3000, 2)
    r = await run_specialist("security", "security", "SYS", plan, llm)
    assert chat.calls == 0 and "nothing to review" in r["trace"][0] and "failed" not in r["stats"][0]


async def test_hallucinated_line_is_dropped(make_llm):
    llm, _, _ = make_llm([ai('{"findings":[{"file":"src/AuthController.java","line":500,"severity":"high","message":"x"}]}')])
    r = await run_specialist("security", "security", "SYS", PLAN, llm)
    assert r["findings"] == [] and "0 finding(s), 1 dropped" in r["trace"][0]


async def test_cache_stores_only_valid_answers(make_llm, tmp_path):
    llm, _, _ = make_llm([ai("garbage"), ai(ONE)], use_cache=True, cache=DiskCache(tmp_path))
    await run_specialist("security", "security", "SYS", PLAN, llm)
    assert len(os.listdir(tmp_path)) == 1          # only the valid retry answer is cached, the garbage is not

    llm2, chat2, _ = make_llm([ai(ONE)], use_cache=True, cache=DiskCache(tmp_path))
    await run_specialist("security", "security", "SYS", PLAN, llm2)
    assert chat2.calls == 1 and len(os.listdir(tmp_path)) == 2   # first-attempt key was a miss; now cached

    llm3, chat3, _ = make_llm([], use_cache=True, cache=DiskCache(tmp_path))
    r3 = await run_specialist("security", "security", "SYS", PLAN, llm3)
    assert chat3.calls == 0 and len(r3["findings"]) == 1          # third run costs zero model calls


async def test_batches_partial_result_and_fatal_stop(make_llm):
    score = lambda path, p: {"A": 9, "B": 8, "C": 7, "D": 6}.get(path[0], 1) if p else 0
    patch = lambda tag: "@@ -1,1 +1,25 @@\n" + "\n".join(f"+int {tag}v{i} = compute({i}) + other({i});" for i in range(25))
    plan = build_plan({f"{c}.java": patch(c) for c in "ABCD"}, score, 600, 2)
    line = lambda b, f: min(plan.batches[b].added[f])
    finding = lambda f, l: ai(json.dumps({"findings": [{"file": f, "line": l, "severity": "low", "message": "m"}]}))
    bad400 = lambda: status_err(groq.BadRequestError, 400)

    llm, chat, _ = make_llm([finding("A.java", line(0, "A.java")), bad400()])        # batch 2 fails -> keep batch 1
    r = await run_specialist("bugs", "bug", "SYS", plan, llm)
    assert len(r["findings"]) == 1 and "failed: batch 2" in r["trace"][0] and "batch 2" in r["stats"][0]["failed"]

    llm, chat, _ = make_llm([bad400(), finding("C.java", line(1, "C.java"))])        # batch 1 fatal -> stop
    r = await run_specialist("bugs", "bug", "SYS", plan, llm)
    assert chat.calls == 1 and "findings" not in r
