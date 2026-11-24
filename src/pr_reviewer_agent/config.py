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
LLM_TPM_LIMIT = int(os.environ.get("LLM_TPM_LIMIT", "7000"))  # real limit is 8000; keep a margin
LLM_MAX_OUTPUT_TOKENS = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "1500"))
LLM_MAX_ATTEMPTS = int(os.environ.get("LLM_MAX_ATTEMPTS", "4"))
LLM_CACHE_ENABLED = os.environ.get("LLM_CACHE", "1") == "1"
LLM_CACHE_DIR = Path(os.environ.get("LLM_CACHE_DIR", ".cache/llm"))
CONVENTIONS_SLICE_TOKENS = int(os.environ.get("CONVENTIONS_SLICE_TOKENS", "2500"))
CONVENTIONS_MAX_SEARCHES = int(os.environ.get("CONVENTIONS_MAX_SEARCHES", "3"))
CONVENTIONS_RESULT_CHARS = int(os.environ.get("CONVENTIONS_RESULT_CHARS", "1500"))