"""Real-Groq check of the critic with 3 hand-made findings. Needs only GROQ_API_KEY: no Spring, no JWT."""
import asyncio

from pr_reviewer_agent import config
from pr_reviewer_agent.critic import apply_verdicts, judge, make_window
from pr_reviewer_agent.llm import UsageTotals, get_llm
from pr_reviewer_agent.schemas import Finding

USER_SERVICE = """public class UserService {
    public User find(Long id) {
        if (id == null) {
            throw new IllegalArgumentException("id");
        }
        User u = repo.findById(id).orElseThrow();
        return u;
    }
}"""
STATS = """public class Stats {
    public int average(List<Integer> xs) {
        int sum = 0;
        for (int x : xs) sum += x;
        return sum / xs.size();
    }
}"""
ADMIN = """@RestController
class AdminController {
    @GetMapping("/admin/users")
    public List<User> all() {
        return service.all();
    }
}"""

# (file content, finding, what we EXPECT from a good critic)
CASES = [
    (USER_SERVICE, Finding(file="UserService.java", line=6, severity="medium", category="bug",
                           message="find() never checks id for null, so repo.findById(id) may throw a NullPointerException."),
     "rejected"),
    (STATS, Finding(file="Stats.java", line=5, severity="medium", category="bug",
                    message="average() divides by xs.size() which is 0 for an empty list, causing ArithmeticException."),
     "confirmed"),
    (ADMIN, Finding(file="AdminController.java", line=4, severity="high", category="security",
                    message="The /admin/users endpoint has no authorization check."),
     "uncertain"),
]


async def main(llm=None) -> list[tuple[str, str, str]]:
    findings = [c[1] for c in CASES]
    windows = [make_window(c[0], c[1].line, config.CRITIC_WINDOW_LINES, config.CRITIC_WINDOW_CHARS) for c in CASES]
    totals = UsageTotals()
    verdicts = await judge(findings, windows, llm or get_llm(), totals)
    _, rejected, _ = apply_verdicts(findings, windows, verdicts)
    rows = []
    for number, (_, finding, expected) in enumerate(CASES, start=1):
        v = verdicts.get(f"F{number}")
        got = v.verdict if v else "(missing)"
        rows.append((finding.file, expected, got))
        print(f"{'OK  ' if got == expected else 'DIFF'} {finding.file}: expected {expected}, got {got} | {v.reason if v else ''}")
    print(totals.summary())
    return rows


if __name__ == "__main__":
    asyncio.run(main())