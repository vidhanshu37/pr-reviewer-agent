from collections.abc import Callable
from dataclasses import dataclass, field

from pr_reviewer_agent.annotate import added_line_numbers, annotate_patch


@dataclass
class DiffSlice:
    text: str = ""
    added: dict[str, set[int]] = field(default_factory=dict)  # file -> added line numbers actually sent
    included: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    truncated: bool = False


def build_slice(files: dict[str, str], score_fn: Callable[[str, str], int], budget_tokens: int) -> DiffSlice:
    """Pick the most relevant files that fit the token budget and annotate them with line numbers."""
    budget_chars = budget_tokens * 4
    ranked = sorted(
        ((score_fn(path, patch), path) for path, patch in files.items()),
        key=lambda item: (-item[0], item[1]),
    )
    result = DiffSlice()
    parts: list[str] = []
    used = 0
    for score, path in ranked:
        if score <= 0:
            continue
        annotated = annotate_patch(files[path])
        if not added_line_numbers(annotated):
            continue  # nothing was added (deletion-only change)
        section = f"### File: {path}\n{annotated}\n\n"
        if used + len(section) > budget_chars:
            if result.included:
                result.skipped.append(path)
                continue
            # first file alone is too big: cut at a line boundary
            section = section[:budget_chars].rsplit("\n", 1)[0] + "\n[truncated]\n\n"
            result.truncated = True
        parts.append(section)
        used += len(section)
        result.included.append(path)
        result.added[path] = added_line_numbers(section)  # only lines the model really saw
    result.text = "".join(parts)
    return result