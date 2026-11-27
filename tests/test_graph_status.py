"""End-to-end through the real LangGraph with a fake LLM and a fake MCP: the failure modes of /review."""
import json

import groq
import pytest
import asyncio
import pr_reviewer_agent.critic as critic_mod
import pr_reviewer_agent.graph as graph_mod
import pr_reviewer_agent.llm as llm_mod
import pr_reviewer_agent.main as main_mod
import pr_reviewer_agent.specialists.conventions as conv_mod
from pr_reviewer_agent.llm import LLMClient
from pr_reviewer_agent.schemas import ReviewRequest
from pr_reviewer_agent.stats import build_stats, compute_status
from tests.helpers import Clock, ai, status_err

pytestmark = pytest.mark.anyio
DIFF = """Pull request #22 in o/r: 3 reviewable file(s) out of 3 changed.

### File: src/main/java/com/x/PrReviewMcpTools.java (modified)
@@ -1,3 +1,8 @@
+public String getFileContent(String path) { return fetch(path); }
+String sql = "select * from t where id=" + id;

### File: src/main/resources/application.properties (modified)
@@ -1,1 +1,2 @@
+mcp.devtoken.enabled=true

### File: src/main/java/com/x/Util.java (added)
@@ -0,0 +1,2 @@
+int a = 1;
"""
SEC = {"findings": [{"file": "src/main/java/com/x/PrReviewMcpTools.java", "line": 2, "severity": "high", "message": "SQL injection"}]}
BUG = {"findings": [{"file": "src/main/java/com/x/Util.java", "line": 1, "severity": "low", "message": "x may be null"}]}


class RoutingChat:
    """Answers by which agent is asking (looks at the system prompt); `fail` maps agent -> Exception."""

    def __init__(self, fail=None):
        self.fail, self.calls = fail or {}, []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        system = messages[0].content
        who = ("security" if "security reviewer" in system else "bugs" if "BUGS" in system
               else "critic" if "verifier" in system else "conventions")
        self.calls.append(who)
        if who in self.fail:
            raise self.fail[who]
        out = {"security": SEC, "bugs": BUG, "conventions": {"findings": []},
               "critic": {"verdicts": [{"id": "F1", "verdict": "confirmed", "reason": ""},
                                       {"id": "F2", "verdict": "rejected", "reason": "L1 shows a null check"}]}}[who]
        return ai(json.dumps(out), 700, 120)


@pytest.fixture
def run_review(monkeypatch):
    async def go(chat, diff=DIFF, mcp_down=False):
        async def fake_call(token, name, args=None):
            if mcp_down:
                raise ConnectionError("mcp down")
            if name in ("get_pr_diff", "get_full_pr_diff"):
                return diff
            return "\n".join(f"line{i}" for i in range(1, 60))        # get_file_content / search_codebase
        for module in (graph_mod, critic_mod, conv_mod):
            monkeypatch.setattr(module, "call_tool", fake_call)
        clock = Clock()
        monkeypatch.setattr(llm_mod, "_client", LLMClient(chat, use_cache=False, time_fn=clock.now,
                                                          sleep_fn=clock.sleep, max_attempts=1))
        return await main_mod.review(ReviewRequest(job_id="t", repo="o/r", pr_number=1, mcp_token="x"))
    return go


async def test_healthy_run_is_done_with_structured_stats(run_review):
    r = await run_review(RoutingChat())
    names = [n["node"] for n in r.stats["nodes"]]
    assert r.status == "done" and r.warnings == [] and r.error is None
    assert names == ["fetch", "triage", "security", "bugs", "conventions", "merge", "critic"]
    assert all("wall_s" in n for n in r.stats["nodes"])
    assert r.stats["totals"]["calls"] == sum(n.get("calls", 0) for n in r.stats["nodes"]) == 4
    assert r.stats["critic"]["confirmed"] == 1 and r.stats["critic"]["rejected"][0]["reason"] == "L1 shows a null check"
    assert [(f.category, f.verdict) for f in r.findings] == [("security", "confirmed")]


async def test_mcp_down_means_failed_not_done(run_review):
    r = await run_review(RoutingChat(), mcp_down=True)
    assert r.status == "failed" and r.findings == [] and r.error and r.warnings == [r.error]


async def test_llm_quota_exhausted_means_partial_never_a_fake_clean_review(run_review):
    quota = status_err(groq.BadRequestError, 400)
    r = await run_review(RoutingChat(fail={"security": quota, "bugs": quota, "conventions": quota}))
    assert r.status == "partial" and r.findings == []
    assert any(w.startswith("security:") for w in r.warnings) and any(w.startswith("bugs:") for w in r.warnings)


async def test_one_specialist_failing_keeps_the_others_findings(run_review):
    r = await run_review(RoutingChat(fail={"security": status_err(groq.BadRequestError, 400)}))
    assert r.status == "partial" and any(f.category == "bug" for f in r.findings)
    assert [w.split(":")[0] for w in r.warnings] == ["security"]


async def test_critic_failure_is_a_warning_but_not_partial(run_review):
    r = await run_review(RoutingChat(fail={"critic": status_err(groq.BadRequestError, 400)}))
    assert r.status == "done" and len(r.findings) == 2 and all(f.verdict is None for f in r.findings)
    assert [w.split(":")[0] for w in r.warnings] == ["critic"]


async def test_docs_only_pr_is_done_with_no_llm_calls(run_review):
    chat = RoutingChat()
    r = await run_review(chat, diff="Pull request #3 in o/r: 1 reviewable file(s) out of 1 changed.\n\n"
                                    "### File: README.md (modified)\n@@ -1 +1,2 @@\n+hello\n")
    assert r.status == "done" and r.findings == [] and chat.calls == []


def test_compute_status_and_build_stats_unit():
    assert compute_status("boom", []) == ("failed", ["boom"])
    assert compute_status(None, [{"node": "security", "skipped": "nothing to review"}]) == ("done", [])
    assert compute_status(None, [{"node": "bugs", "failed": "x"}]) == ("partial", ["bugs: x"])
    assert compute_status(None, [{"node": "critic", "failed": "x"}]) == ("done", ["critic: x"])
    entries = [{"node": "fetch", "wall_s": 1.0},
               {"node": "security", "calls": 2, "cached": 1, "tokens": 1000, "call_s": 3.0, "wait_s": 10.0, "wall_s": 14},
               {"node": "critic", "confirmed": 1, "uncertain": 0, "rejected": 1, "calls": 1, "tokens": 500,
                "call_s": 2.0, "wait_s": 0, "wall_s": 2.5}]
    stats = build_stats(entries, 20.0, [{"file": "a", "line": 1, "reason": "r"}])
    assert stats["totals"] == {"calls": 3, "cached": 1, "tokens": 1500, "call_s": 5.0, "wait_s": 10.0, "wall_s": 20.0}
    assert build_stats([], 0.5, [])["critic"] == {"confirmed": 0, "uncertain": 0, "rejected": []}


class GatedChat(RoutingChat):
    """security only answers AFTER bugs has started: impossible if the nodes run one by one."""

    def __init__(self):
        super().__init__()
        self.bugs_started = asyncio.Event()

    async def ainvoke(self, messages):
        system = messages[0].content
        if "BUGS" in system:
            self.bugs_started.set()
        if "security reviewer" in system:
            await asyncio.wait_for(self.bugs_started.wait(), timeout=2)
        return await super().ainvoke(messages)


async def test_parallel_graph_runs_specialists_together_and_merges_once(run_review, monkeypatch):
    monkeypatch.setattr(main_mod, "review_graph", graph_mod.build_graph(parallel=True))
    chat = GatedChat()
    r = await run_review(chat)
    names = [n["node"] for n in r.stats["nodes"]]
    assert r.status == "done" and r.warnings == []
    assert names[:2] == ["fetch", "triage"] and set(names[2:5]) == {"security", "bugs", "conventions"}
    assert names[5:] == ["merge", "critic"]                      # merge and critic ran once, after all three
    assert sorted(c for c in chat.calls if c != "critic") == ["bugs", "conventions", "security"]
    assert [(f.category, f.verdict) for f in r.findings] == [("security", "confirmed")]


async def test_parallel_graph_one_failure_does_not_stop_the_others(run_review, monkeypatch):
    monkeypatch.setattr(main_mod, "review_graph", graph_mod.build_graph(parallel=True))
    r = await run_review(RoutingChat(fail={"security": status_err(groq.BadRequestError, 400)}))
    assert r.status == "partial" and any(f.category == "bug" for f in r.findings)
    assert [w.split(":")[0] for w in r.warnings] == ["security"]


async def test_parallel_graph_docs_only_goes_straight_to_merge(run_review, monkeypatch):
    monkeypatch.setattr(main_mod, "review_graph", graph_mod.build_graph(parallel=True))
    chat = RoutingChat()
    r = await run_review(chat, diff="Pull request #3 in o/r: 1 reviewable file(s) out of 1 changed.\n\n"
                                    "### File: README.md (modified)\n@@ -1 +1,2 @@\n+hello\n")
    assert r.status == "done" and r.findings == [] and chat.calls == []


async def test_sequential_graph_cannot_pass_the_gate(run_review, monkeypatch):
    """Mutation check: the same GatedChat must FAIL in sequential mode (proves the test really tests parallelism)."""
    monkeypatch.setattr(main_mod, "review_graph", graph_mod.build_graph(parallel=False))
    with pytest.raises(asyncio.TimeoutError):
        await run_review(GatedChat())


async def test_token_breakdown_is_reported(run_review):
    r = await run_review(RoutingChat())
    sec = next(n for n in r.stats["nodes"] if n["node"] == "security")
    assert (sec["in"], sec["out"], sec["reasoning"]) == (700, 120, 20)
    assert r.stats["totals"]["in"] == 700 * 4 and r.stats["totals"]["out"] == 120 * 4