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
