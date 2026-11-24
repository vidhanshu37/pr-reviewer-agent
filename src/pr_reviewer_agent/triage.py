import re

from pr_reviewer_agent.diff_utils import is_test_file

CODE_EXT = (".java", ".py", ".js", ".jsx", ".ts", ".tsx", ".kt", ".go", ".cs", ".rb", ".php", ".dart", ".swift")
CONFIG_NAMES = ("pom.xml", "build.gradle", "dockerfile", "docker-compose", "application.properties",
                "application.yml", "application.yaml", ".env", "package.json", "requirements.txt")
SECURITY_PATH = re.compile(r"auth|security|login|token|jwt|password|crypto|webhook|filter|controller|secret", re.I)
SECURITY_CODE = re.compile(
    r"password|secret|token|api[_-]?key|jdbc:|executeQuery|createQuery|Runtime\.exec|ProcessBuilder"
    r"|\bmd5\b|\bsha1\b|\beval\(|csrf|permitAll|cors",
    re.I,
)

ORDER = ("security", "bugs", "conventions")

def added_lines(patch: str) -> str:
    return "\n".join(l for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))

def select_specialists(files: dict[str, str]) -> list[str]:
    """Rule-based triage: zero tokens, zero latency, deterministic."""
    selected: set[str] = set()
    for path, patch in files.items():
        lower = path.lower()
        is_code = lower.endswith(CODE_EXT)
        is_config = lower.endswith(CONFIG_NAMES) or any(name in lower for name in CONFIG_NAMES)

        if is_code and patch:
            selected.add("bugs")
            if not is_test_file(path):
                selected.add("conventions")
        if is_config or (is_code and SECURITY_PATH.search(path)) or SECURITY_CODE.search(added_lines(patch)):
            selected.add("security")
    return [name for name in ORDER if name in selected]



def security_score(path: str, patch: str) -> int:
    """How worth is this file of a security review? 0 = skip it."""
    lower = path.lower()
    if not patch or is_test_file(path):
        return 0
    score = 0
    if any(name in lower for name in CONFIG_NAMES):
        score += 3
    if lower.endswith(CODE_EXT):
        score += 3 if SECURITY_PATH.search(path) else 1
    if score:
        score += min(len(SECURITY_CODE.findall(added_lines(patch))), 5)
    return score


BUG_CODE = re.compile(r"catch\s*\(|except\b|[!=]=\s*null|\.get\(|\.parse|Thread|synchronized|await |\.close\(|\bnull\b", re.I)

def bugs_score(path: str, patch: str) -> int:
    """Bugs hide in non-test code; bigger changes and risky constructs rank higher. 0 = skip."""
    if not patch or is_test_file(path) or not path.lower().endswith(CODE_EXT):
        return 0
    added = added_lines(patch)
    size_bonus = min(len(added.splitlines()) // 20, 5)
    risk_bonus = min(len(BUG_CODE.findall(added)), 5)
    return 2 + size_bonus + risk_bonus