# config.py
# All application configuration. Secrets and per-environment values come from .env.
# Everything else is hardcoded here so it can be changed without touching logic files.
import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)

# ---- Secrets (from .env) ----
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
EXA_API_KEY    = os.getenv("EXA_API_KEY")
SUPABASE_URL   = os.getenv("SUPABASE_URL")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY")

# ---- Per-environment (from .env) ----
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
PORT = int(os.getenv("PORT", 8000))  # Render auto-injects PORT
HOST = "0.0.0.0"

# ---- Models ----
MAIN_MODEL_NAME   = "llama-3.3-70b-versatile"
REVIEW_MODEL_NAME = "llama-3.1-8b-instant"
TEMPERATURE       = 0.0

# ---- Agent tuning ----
NUM_COUNTRIES        = 3
MAX_REVISION         = 1
MAX_TOOL_ITERATIONS  = 2
MAX_HISTORY          = 10           # message-window per LLM call
AGENT_TIMEOUT_SEC    = 120.0        # per /chat request

# ---- API limits ----
MAX_FILE_BYTES = 5 * 1024 * 1024    # 5 MB upload cap
RATE_LIMIT     = "20/minute"        # per-IP /chat rate limit

# ---- Search tools ----
TAVILY_MAX_RESULTS       = 5
EXA_NUM_RESULTS          = 3
EXA_HIGHLIGHT_MAX_CHARS  = 1000

# ---- Mentor booking ----
MENTOR_BOOKING_COL = "booking_url"
CAL_BASE_URL       = "https://cal.com"

# ---- Dev-only ----
DRAW_GRAPH = os.getenv("DRAW_GRAPH", "false").lower() == "true"

# ---- Required-secret check ----
_missing = [k for k, v in {
    "GROQ_API_KEY": GROQ_API_KEY,
    "TAVILY_API_KEY": TAVILY_API_KEY,
    "EXA_API_KEY": EXA_API_KEY,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
}.items() if not v]
if _missing:
    sys.exit(f"[FATAL] Missing required environment variables: {', '.join(_missing)}")
