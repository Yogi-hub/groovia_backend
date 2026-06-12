# Application configuration. Secrets and per-environment values come from .env.
# Everything else is hardcoded here so it can be changed without touching logic files.
import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)

# Secrets (from .env)
GROQ_API_KEY              = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY            = os.getenv("TAVILY_API_KEY")
EXA_API_KEY               = os.getenv("EXA_API_KEY")
SUPABASE_URL              = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # backend writes bypass RLS with this
SUPABASE_JWT_SECRET       = os.getenv("SUPABASE_JWT_SECRET")        # verify user JWTs locally (no network)
SUPABASE_DB_URL           = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")

# Per-environment
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
PORT = int(os.getenv("PORT", 8000))  # Render auto-injects PORT
HOST = "0.0.0.0"
# Where the frontend lives — used to build links inside LLM responses (e.g. "browse all mentors").
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")

# Models
MAIN_MODEL_NAME   = "llama-3.1-8b-instant"
REVIEW_MODEL_NAME = "llama-3.1-8b-instant"
TEMPERATURE       = 0.0

# Agent tuning
NUM_COUNTRIES        = 3
MAX_REVISION         = 1
MAX_TOOL_ITERATIONS  = 3
MAX_HISTORY          = 5           # message-window per LLM call
AGENT_TIMEOUT_SEC    = 120.0       # per /chat request

# API limits
MAX_FILE_BYTES = 5 * 1024 * 1024   # 5 MB upload cap
RATE_LIMIT     = "20/minute"       # per-IP /chat rate limit

# Search tools
TAVILY_MAX_RESULTS       = 5
EXA_NUM_RESULTS          = 3
EXA_HIGHLIGHT_MAX_CHARS  = 1000

# Mentor booking
MENTOR_BOOKING_COL = "booking_url"
CAL_BASE_URL       = "https://cal.com"
# HMAC secret for verifying inbound Cal.com webhooks. Optional — the /webhooks/cal
# endpoint returns 503 until it's set, everything else runs fine without it.
CAL_WEBHOOK_SECRET = os.getenv("CAL_WEBHOOK_SECRET")

# Feature flags. Default ON. Override with env var per environment.
# Frontend has a parallel set in groovia-frontend/lib/features.ts — keep them in sync.
def _flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")

FEATURE_CHAT_HISTORY    = _flag("FEATURE_CHAT_HISTORY")     # Recent-chats sidebar list
FEATURE_GUEST_MODE      = _flag("FEATURE_GUEST_MODE")       # Chat works without sign-in until resume upload
FEATURE_MENTORS_PUBLIC  = _flag("FEATURE_MENTORS_PUBLIC")   # Anyone can browse /mentors
FEATURE_WEB_SEARCH_TOOL = _flag("FEATURE_WEB_SEARCH_TOOL")  # Agent can call Tavily + Exa
FEATURE_MENTOR_TOOL     = _flag("FEATURE_MENTOR_TOOL")      # Agent can call retrieve_matching_mentors
FEATURE_RESUME_UPLOAD   = _flag("FEATURE_RESUME_UPLOAD")    # Upload control on chat composer
FEATURE_GOOGLE_OAUTH    = _flag("FEATURE_GOOGLE_OAUTH")     # Show "Continue with Google" button

# Dev-only
DRAW_GRAPH = os.getenv("DRAW_GRAPH", "false").lower() == "true"

# Fail fast if any required secret is missing.
_missing = [k for k, v in {
    "GROQ_API_KEY": GROQ_API_KEY,
    "TAVILY_API_KEY": TAVILY_API_KEY,
    "EXA_API_KEY": EXA_API_KEY,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_SERVICE_ROLE_KEY": SUPABASE_SERVICE_ROLE_KEY,
    "SUPABASE_JWT_SECRET": SUPABASE_JWT_SECRET,
    "SUPABASE_DB_URL (or DATABASE_URL)": SUPABASE_DB_URL,
}.items() if not v]
if _missing:
    sys.exit(f"[FATAL] Missing required environment variables: {', '.join(_missing)}")
