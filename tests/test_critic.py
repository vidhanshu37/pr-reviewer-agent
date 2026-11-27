import json

import pytest

import pr_reviewer_agent.critic as critic
from pr_reviewer_agent.critic import Verdict, apply_verdicts, make_window, run_critic
from pr_reviewer_agent.schemas import Finding
from tests.helpers import ai

pytestmark = pytest.mark.anyio
F = lambda f, l, sev="medium", cat="bug": Finding(file=f, line=l, severity=sev, category=cat, message=f"msg {f}:{l}")
V = lambda *items: ai(json.dumps({"verdicts": [{"id": i, "verdict": v, "reason": r} for i, v, r in items]}))


def test_window_is_numbered_marks_the_line_and_handles_edges():
    content = "\n".join(f"c{i}" for i in range(1, 31))
    assert make_window(content, 15, 2, 1200).splitlines() == [
        "L13    c13", "L14    c14", "L15 >> c15", "L16    c16", "L17    c17"]
    assert make_window(content, 1, 2, 1200).startswith("L1 >>")
    assert make_window(content, 99, 2, 1200) is None and make_window(content, None, 2, 1200) is None
    assert len(make_window(content, 15, 12, 20)) <= 20


def test_apply_verdicts_rules_are_enforced_by_code_not_by_the_model():
    findings = [F("a", 1), F("b", 2), F("c", 3), F("d", 4), F("e", 5)]
    windows = ["w", "w", "w", None, "w"]
    verdicts = {"F1": Verdict(id="F1", verdict="confirmed"),
                "F2": Verdict(id="F2", verdict="rejected", reason="null check on L2"),
                "F3": Verdict(id="F3", verdict="rejected", reason=""),      # no reason  -> uncertain
                "F4": Verdict(id="F4", verdict="confirmed", reason="x")}    # no window  -> uncertain ; F5 missing -> uncertain
    kept, rejected, counts = apply_verdicts(findings, windows, verdicts)
    assert [r["file"] for r in rejected] == ["b"] and rejected[0]["reason"]
    assert counts == {"confirmed": 1, "uncertain": 3, "rejected": 1}
    assert [f.verdict for f in kept] == ["confirmed", "uncertain", "uncertain", "uncertain"]


@pytest.fixture
def files(monkeypatch):
    fetched = []

    async def fake_call(token, name, args=None):
        fetched.append(args["path"])
        return "ERROR[not_found]: x" if args["path"] == "gone.java" else "\n".join(f"l{i}" for i in range(1, 40))
    monkeypatch.setattr(critic, "call_tool", fake_call)
    return fetched


async def test_critic_fetches_each_file_once_and_applies_verdicts(make_llm, files):
    merged = [F("a.java", 5, "high"), F("a.java", 9), F("b.java", 3, "low"), F("gone.java", 4)]
    llm, chat, _ = make_llm([V(("F1", "confirmed", ""), ("F2", "rejected", "L8 shows null check"),
                               ("F3", "uncertain", ""), ("F4", "confirmed", ""))])
    r = await run_critic("T", merged, llm)
    assert sorted(files) == ["a.java", "b.java", "gone.java"] and chat.calls == 1
    assert [f.line for f in r["merged"]] == [5, 3, 4] and [x["line"] for x in r["rejected"]] == [9]
    assert r["merged"][2].verdict == "uncertain"                    # gone.java: no window -> never confirmed
    assert "(not available)" in chat.seen[0][1].content and "L5 >>" in chat.seen[0][1].content
    assert r["stats"][0]["rejected"] == 1


async def test_critic_retries_bad_json_once(make_llm, files):
    llm, chat, _ = make_llm([ai("oops"), V(("F1", "confirmed", ""))])
    r = await run_critic("T", [F("a.java", 5)], llm)
    assert chat.calls == 2 and r["merged"][0].verdict == "confirmed"


async def test_critic_fails_open_and_marks_failed(make_llm, files, monkeypatch):
    llm, _, _ = make_llm([ai("oops"), ai("nope")])
    r = await run_critic("T", [F("a.java", 5)], llm)
    assert "merged" not in r and "critic returned invalid JSON" in r["stats"][0]["failed"]

    llm, chat, _ = make_llm([])
    r = await run_critic("T", [F("gone.java", 4)], llm)              # no file content at all -> no LLM call
    assert chat.calls == 0 and "merged" not in r and "failed" in r["stats"][0]

    async def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(critic, "call_tool", boom)
    r = await run_critic("T", [F("a.java", 5)], llm)
    assert "merged" not in r and "failed" in r["stats"][0]


async def test_critic_nothing_to_verify_is_not_a_failure(make_llm, files):
    llm, _, _ = make_llm([])
    r = await run_critic("T", [], llm)
    assert r["trace"] == ["critic: nothing to verify"] and "failed" not in r["stats"][0]


async def test_critic_caps_findings_and_leaves_the_rest_unchecked(make_llm, files):
    many = [F("a.java", i + 1) for i in range(12)]
    llm, _, _ = make_llm([V(*[(f"F{i}", "confirmed", "") for i in range(1, 11)])])
    r = await run_critic("T", many, llm)
    assert len(r["merged"]) == 12 and r["merged"][11].verdict is None and "2 not checked" in r["trace"][0]


def test_worst_case_prompt_fits_the_token_budget():
    prompt = critic.build_prompt([F("a.java", 20) for _ in range(10)], ["x" * 1200] * 10)
    assert (len(prompt) + len(critic.CRITIC_SYSTEM)) // 4 < 4500
