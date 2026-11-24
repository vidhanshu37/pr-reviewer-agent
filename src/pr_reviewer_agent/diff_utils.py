import re

FILE_HEADER = re.compile(r"^### File: (.+?) \((\w+)\)$", re.MULTILINE)
OVERFLOW_HEADER = "### OTHER MODIFIED FILES"

def parse_diff(diff: str) -> dict[str, str]:
    """Split the compressed diff from get_pr_diff into {path: patch}.

   Files that overflowed the token budget on the Spring side come back
   name-only, so they map to an empty patch.
   """
    files: dict[str, str] = {}
    headers = list(FILE_HEADER.finditer(diff))

    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(diff)
        body = diff[header.end():end]
        cut = body.find("\n### ")
        if cut != -1:
            body = body[:cut]
        files[header.group(1)] = body.strip()

    overflow = diff.find(OVERFLOW_HEADER)
    if overflow != -1:
        for line in diff[overflow:].splitlines()[1:]:
            if line.startswith("### "):
                break
            if line.startswith("- "):
                files.setdefault(line[2:].strip(), "")
    return files

def is_test_file(path: str) -> bool:
    lower = path.lower()
    return (
            "/test/" in lower
            or "/tests/" in lower
            or lower.endswith(("test.java", "tests.java", "_test.py", ".test.js", ".test.ts", ".spec.ts"))
            or "/test_" in lower
    )