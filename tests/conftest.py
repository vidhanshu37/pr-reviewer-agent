import pytest

from pr_reviewer_agent.llm import LLMClient
from tests.helpers import Clock, FakeChat


@pytest.fixture
def anyio_backend():
    return "asyncio"  # run `@pytest.mark.anyio` tests on asyncio only


@pytest.fixture
def make_llm():
    """make_llm(script, **kw) -> (LLMClient, FakeChat, Clock); cache off unless asked."""
    def factory(script, **kw):
        clock, chat = Clock(), FakeChat(script)
        kw.setdefault("use_cache", False)
        llm = LLMClient(chat, time_fn=clock.now, sleep_fn=clock.sleep, tpm_limit=kw.pop("tpm_limit", 7000),
                        max_output_tokens=kw.pop("max_output_tokens", 1500), **kw)
        return llm, chat, clock
    return factory
