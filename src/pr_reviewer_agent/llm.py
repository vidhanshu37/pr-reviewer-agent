import asyncio
import hashlib
import json
import random
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

import groq
from langchain_core.messages import BaseMessage

from pr_reviewer_agent import config


class LLMError(Exception):
    """The LLM call cannot succeed (bad request, empty answer, retries exhausted)."""


@dataclass
class CallUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    latency_s: float = 0.0
    waited_s: float = 0.0  # time spent waiting for the rate limiter / backoff


@dataclass
class LLMResult:
    content: str
    usage: CallUsage
    cached: bool = False
    attempts: int = 1


@dataclass
class UsageTotals:
    calls: int = 0
    cache_hits: int = 0
    total_tokens: int = 0
    latency_s: float = 0.0
    waited_s: float = 0.0

    def add(self, result: LLMResult) -> None:
        self.calls += 1
        self.cache_hits += 1 if result.cached else 0
        self.total_tokens += result.usage.total_tokens
        self.latency_s += result.usage.latency_s
        self.waited_s += result.usage.waited_s

    def summary(self) -> str:
        return (f"llm: {self.calls} call(s), {self.cache_hits} cached, "
                f"{self.total_tokens} tokens, {self.latency_s:.1f}s call + {self.waited_s:.1f}s wait")


def estimate_tokens(messages: list[BaseMessage]) -> int:
    chars = sum(len(_text_of(m.content)) for m in messages)
    return chars // 4 + 4 * len(messages)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)


class TokenWindow:
    """Sliding 60 s window of tokens used, so we stay under Groq's tokens-per-minute limit.

    Callers reserve an ESTIMATE before the call and settle with the ACTUAL usage after it.
    The lock is held while waiting, so concurrent callers go one by one (what we want here).
    """

    def __init__(self, limit: int, time_fn=time.monotonic, sleep_fn=asyncio.sleep, window_s: float = 60.0):
        self._limit = limit
        self._time = time_fn
        self._sleep = sleep_fn
        self._window_s = window_s
        self._entries: deque[list[float]] = deque()  # [timestamp, tokens]
        self._lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        while self._entries and now - self._entries[0][0] >= self._window_s:
            self._entries.popleft()

    async def reserve(self, estimate: int) -> tuple[list[float], float]:
        waited = 0.0
        async with self._lock:
            while True:
                now = self._time()
                self._prune(now)
                used = sum(entry[1] for entry in self._entries)
                # An empty window always lets one call through, even if it alone exceeds the limit.
                if not self._entries or used + estimate <= self._limit:
                    entry = [now, float(estimate)]
                    self._entries.append(entry)
                    return entry, waited
                wait = max(self._entries[0][0] + self._window_s - now, 0.05)
                await self._sleep(wait)
                waited += wait

    @staticmethod
    def settle(entry: list[float], actual: int) -> None:
        entry[1] = float(actual)


class DiskCache:
    """Content-addressed cache: same model + messages + params -> same answer, zero tokens."""

    def __init__(self, directory: Path):
        self._dir = Path(directory)

    @staticmethod
    def key(model: str, messages: list[BaseMessage], params: dict) -> str:
        payload = json.dumps(
            {"model": model, "params": params, "messages": [[m.type, _text_of(m.content)] for m in messages]},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict | None:
        try:
            return json.loads((self._dir / f"{key}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, key: str, value: dict) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            (self._dir / f"{key}.json").write_text(json.dumps(value), encoding="utf-8")
        except OSError:
            pass  # cache is best-effort


def _retry_after(exc: groq.APIStatusError) -> float | None:
    try:
        return min(float(exc.response.headers.get("retry-after")), 120.0)
    except (TypeError, ValueError, AttributeError):
        return None


def _backoff(attempt: int) -> float:
    return min(2.0 ** attempt, 30.0) + random.uniform(0, 0.5)


class LLMClient:
    def __init__(
            self,
            chat=None,
            *,
            model: str | None = None,
            tpm_limit: int | None = None,
            max_output_tokens: int | None = None,
            max_attempts: int | None = None,
            cache: DiskCache | None = None,
            use_cache: bool | None = None,
            time_fn=time.monotonic,
            sleep_fn=asyncio.sleep,
    ):
        self._chat = chat
        self._model = model or config.GROQ_MODEL
        self._max_output = max_output_tokens or config.LLM_MAX_OUTPUT_TOKENS
        self._max_attempts = max_attempts or config.LLM_MAX_ATTEMPTS
        self._time = time_fn
        self._sleep = sleep_fn
        self._window = TokenWindow(tpm_limit or config.LLM_TPM_LIMIT, time_fn, sleep_fn)
        enabled = config.LLM_CACHE_ENABLED if use_cache is None else use_cache
        self._cache = (cache or DiskCache(config.LLM_CACHE_DIR)) if enabled else None

    def _chat_model(self):
        if self._chat is None:
            from langchain_groq import ChatGroq  # imported lazily so tests/imports need no API key

            kwargs = {
                "model": self._model,
                "temperature": 0,
                "max_tokens": self._max_output,
                "max_retries": 0,  # retries are OUR job (pacing + retry-after aware)
                "timeout": config.GROQ_TIMEOUT_S,
            }
            if config.GROQ_REASONING_EFFORT:
                kwargs["reasoning_effort"] = config.GROQ_REASONING_EFFORT
            self._chat = ChatGroq(**kwargs)
        return self._chat

    async def ainvoke(self, messages: list[BaseMessage]) -> LLMResult:
        params = {"temperature": 0, "max_tokens": self._max_output, "reasoning_effort": config.GROQ_REASONING_EFFORT}
        key = DiskCache.key(self._model, messages, params) if self._cache else None
        if key:
            hit = self._cache.get(key)
            if hit and hit.get("content"):
                return LLMResult(hit["content"], CallUsage(), cached=True, attempts=0)

        estimate = estimate_tokens(messages) + self._max_output
        waited_total = 0.0
        last_reason = "unknown"

        for attempt in range(1, self._max_attempts + 1):
            entry, waited = await self._window.reserve(estimate)
            waited_total += waited
            started = self._time()
            try:
                response = await self._chat_model().ainvoke(messages)
            except groq.RateLimitError as exc:
                self._window.settle(entry, 0)
                last_reason = "rate_limited"
                delay = _retry_after(exc) or _backoff(attempt)
            except groq.APIStatusError as exc:
                self._window.settle(entry, 0)
                if exc.status_code < 500:
                    raise LLMError(f"LLM request rejected (HTTP {exc.status_code})") from None
                last_reason = f"http_{exc.status_code}"
                delay = _backoff(attempt)
            except groq.APIConnectionError as exc:  # includes timeouts
                self._window.settle(entry, 0)
                last_reason = type(exc).__name__
                delay = _backoff(attempt)
            else:
                latency = self._time() - started
                text = _text_of(response.content)
                usage = _usage_from(response, latency, waited_total, estimate)
                self._window.settle(entry, usage.total_tokens)
                if not text.strip():
                    raise LLMError("LLM returned an empty answer (reasoning may have used the whole output budget)")
                if key:
                    self._cache.put(key, {"content": text, "usage": asdict(usage)})
                return LLMResult(text, usage, cached=False, attempts=attempt)

            if attempt < self._max_attempts:
                await self._sleep(delay)
                waited_total += delay

        raise LLMError(f"LLM call failed after {self._max_attempts} attempts ({last_reason})")


def _usage_from(response, latency: float, waited: float, estimate: int) -> CallUsage:
    meta = getattr(response, "usage_metadata", None) or {}
    details = meta.get("output_token_details") or {}
    input_tokens = int(meta.get("input_tokens", 0))
    output_tokens = int(meta.get("output_tokens", 0))
    total = int(meta.get("total_tokens") or (input_tokens + output_tokens) or estimate)
    return CallUsage(input_tokens, output_tokens, int(details.get("reasoning", 0)), total, latency, waited)


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client