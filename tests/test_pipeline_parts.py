from pr_reviewer_agent.annotate import added_line_numbers, annotate_patch
from pr_reviewer_agent.merge import merge_findings
from pr_reviewer_agent.schemas import Finding
from pr_reviewer_agent.slicing import build_plan
from pr_reviewer_agent.triage import bugs_score, conventions_score, security_score, select_specialists

PATCH = """@@ -10,3 +10,5 @@ class AuthController {
     String a = "x";
+    String sql = "select * from users where id=" + id;
+    log.info("token=" + token);
     return ok;
@@ -40,2 +42,2 @@ void other() {
-    old();
+    fresh();
     done();"""


def test_annotate_uses_new_file_line_numbers():
    annotated = annotate_patch(PATCH)
    assert added_line_numbers(annotated) == {11, 12, 42}
    assert "L11 + " in annotated and "    - " in annotated and "    ..." in annotated


def test_annotate_edge_cases():
    assert annotate_patch("") == "" and annotate_patch("garbage") == ""
    assert "No newline" not in annotate_patch("@@ -1 +1 @@\n+x\n\\ No newline at end of file")


def test_scores_rank_risky_files_and_ignore_tests_and_docs():
    assert security_score("src/AuthController.java", PATCH) > security_score("src/Util.java", PATCH) > 0
    for score in (security_score, bugs_score, conventions_score):
        assert score("src/test/UtilTest.java", PATCH) == 0 and score("README.md", PATCH) == 0
    assert security_score("pom.xml", "@@ -1 +1 @@\n+<x/>") >= 3


def test_triage_selects_specialists_by_rules():
    assert select_specialists({"README.md": "@@ -1 +1 @@\n+x"}) == []
    picked = select_specialists({"src/AuthController.java": PATCH})
    assert picked == ["security", "bugs", "conventions"]


def _patch(n, tag=""):
    return f"@@ -1,1 +1,{n} @@\n" + "\n".join(f"+int {tag}v{i} = compute({i}) + other({i});" for i in range(n))


def test_slicing_packs_best_files_first_and_caps_batches():
    score = lambda path, p: {"A": 9, "B": 8, "C": 7, "D": 6, "E": 5}.get(path[0], 1) if p else 0
    files = {f"{c}.java": _patch(25, c) for c in "ABCDE"}
    plan = build_plan(files, score, 600, 2)
    assert len(plan.batches) == 2 and plan.batches[0].included[0] == "A.java"
    assert plan.not_reviewed == ["E.java"] and plan.eligible == 5
    assert all(len(b.text) <= 2400 + 20 for b in plan.batches)
    assert build_plan(files, score, 600, 1).not_reviewed == ["C.java", "D.java", "E.java"]


def test_slicing_truncates_giant_file_into_its_own_batch():
    score = lambda path, p: 9 if path[0] == "A" else 1
    plan = build_plan({"A.java": _patch(400, "A"), "B.java": _patch(5, "B")}, score, 600, 2)
    assert plan.batches[0].truncated and plan.batches[0].included == ["A.java"]
    assert max(plan.batches[0].added["A.java"]) < 400
    assert build_plan({"R.md": ""}, score, 600, 2).batches == []


def test_merge_keeps_most_severe_per_line_and_sorts():
    F = lambda f, l, sev, cat: Finding(file=f, line=l, severity=sev, category=cat, message=f"{cat}-{sev}")
    merged, dups = merge_findings([
        F("a", 5, "medium", "security"), F("a", 5, "high", "bug"),
        F("b", 2, "low", "security"), F("b", 2, "low", "bug"),
        F("c", 9, "critical", "bug"), F("c", None, "low", "bug")])
    assert dups == 2 and [(m.file, m.line) for m in merged] == [("c", 9), ("a", 5), ("b", 2), ("c", None)]
    assert merged[1].message == "bug-high" and merged[2].message == "security-low"
    assert merge_findings([]) == ([], 0)
