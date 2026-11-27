import asyncio
import time

from langchain_core.messages import HumanMessage, SystemMessage

from pr_reviewer_agent.llm import UsageTotals, get_llm

async def main() -> None:
    llm = get_llm()
    totals = UsageTotals()
    messages = [
        SystemMessage(content="You are a terse code reviewer."),
        HumanMessage(content="In one sentence: why is string-concatenated SQL dangerous?"),
    ]
    for label in ("first call (real)", "second call (cache)"):
        started = time.monotonic()
        result = await llm.ainvoke(messages)
        totals.add(result)
        print(f"[{label}] cached={result.cached} attempts={result.attempts} "
              f"tokens={result.usage.total_tokens} (reasoning={result.usage.reasoning_tokens}) "
              f"took={time.monotonic() - started:.2f}s")
        print("  ", result.content[:200])
    print(totals.summary())


asyncio.run(main())