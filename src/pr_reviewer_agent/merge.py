from pr_reviewer_agent.schemas import Finding

RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

def merge_findings(findings: list[Finding]) -> tuple[list[Finding], int]:
    """One finding per (file, line): keep the most severe; on a tie the earlier specialist wins.
    Result is sorted most severe first, then by file and line. Returns (merged, duplicates_dropped)."""
    best: dict[tuple[str, int | None], Finding] = {}
    for finding in findings:
        key = (finding.file, finding.line)
        current = best.get(key)
        if current is None or RANK[finding.severity] > RANK[current.severity]:
            best[key] = finding
    merged = sorted(best.values(), key=lambda f: (-RANK[f.severity], f.file, f.line or 0))
    return merged, len(findings) - len(merged)