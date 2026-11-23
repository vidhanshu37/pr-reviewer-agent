import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MCP_URL = os.environ.get("MCP_URL", "http://localhost:8081/mcp")

# --- LLM (Groq free tier) ---
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_REASONING_EFFORT = os.environ.get("GROQ_REASONING_EFFORT", "low")
GROQ_TIMEOUT_S = float(os.environ.get("GROQ_TIMEOUT_S", "60"))
LLM_TPM_LIMIT = int(os.environ.get("LLM_TPM_LIMIT", "7000"))  # real limit is 8000; keep a margin
LLM_MAX_OUTPUT_TOKENS = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "1500"))
LLM_MAX_ATTEMPTS = int(os.environ.get("LLM_MAX_ATTEMPTS", "4"))
LLM_CACHE_ENABLED = os.environ.get("LLM_CACHE", "1") == "1"
LLM_CACHE_DIR = Path(os.environ.get("LLM_CACHE_DIR", ".cache/llm"))