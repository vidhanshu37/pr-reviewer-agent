from pr_reviewer_agent.triage import ORDER


def compute_status(error: str | None, entries: list[dict]) -> tuple[str, list[str]]:
    """done = everything ran | partial = a specialist failed (findings may be incomplete) | failed = no review at all.

    A failed critic only adds a warning: its findings are unverified, but 'no issues' can never come from it."""
    if error:
        return "failed", [error]
    warnings = [f"{e['node']}: {e['failed']}" for e in entries if e.get("failed")]
    specialist_failed = any(e.get("failed") and e.get("node") in ORDER for e in entries)
    return ("partial" if specialist_failed else "done"), warnings


def build_stats(entries: list[dict], wall_s: float, rejected: list[dict]) -> dict:
    """Turn the per-node entries (state["stats"]) into one summary object for the response."""
    keys = ("calls", "cached", "tokens", "call_s", "wait_s")
    keys += tuple(k for k in ("in", "out", "reasoning") if any(k in e for e in entries))  # token breakdown, if reported
    totals = {k: round(sum(e.get(k, 0) for e in entries), 2) for k in keys}
    totals["wall_s"] = round(wall_s, 2)
    critic = next((e for e in entries if e.get("node") == "critic"), {})
    return {
        "totals": totals,
        "nodes": entries,
        "critic": {
            "confirmed": critic.get("confirmed", 0),
            "uncertain": critic.get("uncertain", 0),
            "rejected": rejected,
            **({"failed": critic["failed"]} if "failed" in critic else {}),
        },
    }