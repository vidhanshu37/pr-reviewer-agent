def build_stats(entries: list[dict], wall_s: float, rejected: list[dict]) -> dict:
    """Turn the per-node entries (state["stats"]) into one summary object for the response."""
    keys = ("calls", "cached", "tokens", "call_s", "wait_s")
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
            **({"skipped": critic["skipped"]} if "skipped" in critic else {}),
        },
    }