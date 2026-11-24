import re

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
ADDED_LINE = re.compile(r"^L(\d+) \+ ", re.MULTILINE)


def annotate_patch(patch: str) -> str:
    """Rewrite a unified-diff patch so every ADDED line carries its new-file line number.

        L42 + String sql = ...      <- added line, number is the line in the new file
            return ok;              <- unchanged context
            - oldCode();            <- removed line

    The model copies numbers instead of counting hunk offsets (which LLMs get wrong).
    """
    out: list[str] = []
    new_line = 0
    in_hunk = False
    hunks_seen = 0
    for raw in patch.splitlines():
        match = HUNK.match(raw)
        if match:
            new_line = int(match.group(1))
            in_hunk = True
            if hunks_seen:
                out.append("    ...")
            hunks_seen += 1
            continue
        if not in_hunk or raw.startswith("\\"):  # "\ No newline at end of file"
            continue
        if raw.startswith("+"):
            out.append(f"L{new_line} + {raw[1:]}")
            new_line += 1
        elif raw.startswith("-"):
            out.append(f"    - {raw[1:]}")
        else:
            out.append(f"    {raw[1:]}")
            new_line += 1
    return "\n".join(out)


def added_line_numbers(annotated: str) -> set[int]:
    return {int(n) for n in ADDED_LINE.findall(annotated)}