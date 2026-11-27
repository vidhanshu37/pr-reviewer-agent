from collections.abc import Callable
from dataclasses import dataclass, field

from pr_reviewer_agent.annotate import added_line_numbers, annotate_patch


@dataclass
class DiffSlice:
    """One LLM call's worth of diff."""

    text: str = ""
    added: dict[str, set[int]] = field(default_factory=dict)  # file -> added line numbers actually sent
    included: list[str] = field(default_factory=list)
    truncated: bool = False


@dataclass
class SlicePlan:
    batches: list[DiffSlice] = field(default_factory=list)
    not_reviewed: list[str] = field(default_factory=list)  # eligible files that did not fit any batch

    @property
    def eligible(self) -> int:
        return sum(len(batch.included) for batch in self.batches) + len(self.not_reviewed)


def build_plan(files: dict[str, str], score_fn: Callable[[str, str], int],
               budget_tokens: int, max_batches: int) -> SlicePlan:
    """Rank files, then pack them into at most `max_batches` batches of ~budget_tokens each.

    Best-scored files are placed first, so they land in the first batches and the cap drops the least
    relevant ones. Anything that does not fit is listed in `not_reviewed` (never silently lost).
    """
    budget_chars = budget_tokens * 4
    ranked = sorted(
        ((score_fn(path, patch), path) for path, patch in files.items()),
        key=lambda item: (-item[0], item[1]),
    )
    plan = SlicePlan()
    parts: list[list[str]] = []
    used: list[int] = []

    for score, path in ranked:
        if score <= 0:
            continue
        annotated = annotate_patch(files[path])
        if not added_line_numbers(annotated):
            continue  # nothing was added (deletion-only change)
        section = f"### File: {path}\n{annotated}\n\n"

        # first-fit: the first batch that still has room
        target = next((i for i, size in enumerate(used) if size + len(section) <= budget_chars), None)
        truncated = False
        if target is None:
            if len(plan.batches) >= max_batches:
                plan.not_reviewed.append(path)
                continue
            if len(section) > budget_chars:  # one file bigger than a whole batch: cut at a line boundary
                section = section[:budget_chars].rsplit("\n", 1)[0] + "\n[truncated]\n\n"
                truncated = True
            plan.batches.append(DiffSlice())
            parts.append([])
            used.append(0)
            target = len(plan.batches) - 1

        batch = plan.batches[target]
        parts[target].append(section)
        used[target] += len(section)
        batch.included.append(path)
        batch.truncated = batch.truncated or truncated
        batch.added[path] = added_line_numbers(section)  # only lines the model really saw

    for batch, sections in zip(plan.batches, parts):
        batch.text = "".join(sections)
    return plan