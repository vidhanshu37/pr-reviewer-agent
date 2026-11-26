import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MCP_URL = os.environ.get("MCP_URL", "http://localhost:8081/mcp")

# --- LLM (Groq free tier) ---
SPECIALIST_SLICE_TOKENS = int(os.environ.get("SPECIALIST_SLICE_TOKENS", "3000"))
SPECIALIST_MAX_BATCHES = int(os.environ.get("SPECIALIST_MAX_BATCHES", "2"))
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_REASONING_EFFORT = os.environ.get("GROQ_REASONING_EFFORT", "low")
GROQ_TIMEOUT_S = float(os.environ.get("GROQ_TIMEOUT_S", "60"))
NVIDIA_MEDIUM_EFFORT = os.environ.get("NVIDIA_MEDIUM_EFFORT", "0") == "1"  # only used when thinking is on
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "groq").lower()
LLM_TPM_LIMIT = int(os.environ.get("LLM_TPM_LIMIT", "7000"))  # real limit is 8000; keep a margin
LLM_MAX_OUTPUT_TOKENS = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "1500"))
LLM_MAX_ATTEMPTS = int(os.environ.get("LLM_MAX_ATTEMPTS", "4"))
LLM_CACHE_ENABLED = os.environ.get("LLM_CACHE", "1") == "1"
LLM_CACHE_DIR = Path(os.environ.get("LLM_CACHE_DIR", ".cache/llm"))
CONVENTIONS_SLICE_TOKENS = int(os.environ.get("CONVENTIONS_SLICE_TOKENS", "2500"))
CONVENTIONS_MAX_SEARCHES = int(os.environ.get("CONVENTIONS_MAX_SEARCHES", "3"))
CONVENTIONS_RESULT_CHARS = int(os.environ.get("CONVENTIONS_RESULT_CHARS", "1500"))
CRITIC_MAX_FILES = int(os.environ.get("CRITIC_MAX_FILES", "6"))
CRITIC_MAX_FINDINGS = int(os.environ.get("CRITIC_MAX_FINDINGS", "10"))
CRITIC_WINDOW_LINES = int(os.environ.get("CRITIC_WINDOW_LINES", "12"))
CRITIC_WINDOW_CHARS = int(os.environ.get("CRITIC_WINDOW_CHARS", "1200"))

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "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")
NVIDIA_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
NVIDIA_THINKING = os.environ.get("NVIDIA_THINKING", "0") == "1"  # off = faster, answer comes straight in `content`
NVIDIA_TIMEOUT_S = float(os.environ.get("NVIDIA_TIMEOUT_S", "120"))

LLM_MODEL = NVIDIA_MODEL if LLM_PROVIDER == "nvidia" else GROQ_MODEL

AGENT_PARALLEL = os.environ.get("AGENT_PARALLEL", "0") == "1"