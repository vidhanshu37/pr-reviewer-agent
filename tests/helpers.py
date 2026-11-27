import httpx
from langchain_core.messages import AIMessage

REQ = httpx.Request("POST", "https://api.groq.com/x")


def status_err(cls, code, headers=None, body=None):
    return cls("boom", response=httpx.Response(code, headers=headers or {}, request=REQ), body=body)


def ai(text, inp=100, out=50, reasoning=20):
    return AIMessage(content=text, usage_metadata={"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out,
                                                  "output_token_details": {"reasoning": reasoning}})


def tool_ai(*queries):
    calls = [{"name": "search_codebase", "args": {"query": q}, "id": f"c{i}"} for i, q in enumerate(queries)]
    return AIMessage(content="", tool_calls=calls,
                     usage_metadata={"input_tokens": 900, "output_tokens": 50, "total_tokens": 950})


class FakeChat:
    """Scripted stand-in for ChatGroq: each ainvoke pops the next item (AIMessage or Exception)."""

    def __init__(self, script):
        self.script, self.calls, self.seen, self.bound = list(script), 0, [], None

    def bind_tools(self, tools):
        self.bound = tools
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        self.seen.append(messages)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Clock:
    """Fake time: sleep() just moves the clock, so rate-limit tests take 0 real seconds."""

    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    async def sleep(self, seconds):
        self.sleeps.append(round(seconds, 2))
        self.t += seconds
