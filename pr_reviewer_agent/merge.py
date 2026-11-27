from pr_reviewer_agent.schemas import Finding

RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _priority(f: Finding) -> tuple[bool, int]:
    """Lower is better: sure findings before 'possible' ones, then most severe first."""
    return f.confidence == "possible", -RANK[f.severity]

def merge_findings(findings: list[Finding]) -> tuple[list[Finding], int]:
    """One finding per (file, line): keep the best (sure before possible, then most severe); on a tie the earlier specialist wins.
    Result is sorted sure-first, then most severe, then by file and line. Returns (merged, duplicates_dropped)."""
    best: dict[tuple[str, int | None], Finding] = {}
    for finding in findings:
        key = (finding.file, finding.line)
        current = best.get(key)
        if current is None or _priority(finding) < _priority(current):
            best[key] = finding
    merged = sorted(best.values(), key=lambda f: (*_priority(f), f.file, f.line or 0))
    return merged, len(findings) - len(merged)