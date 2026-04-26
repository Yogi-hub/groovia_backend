# config.py
import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
EXA_API_KEY = os.getenv("EXA_API_KEY")

MAIN_MODEL_NAME = "meta-llama/llama-4-scout-17b-16e-instruct"
FALLBACK_MODEL_NAME = "meta-llama/llama-4-scout-17b-16e-instruct"
TEMPERATURE = 0.0

NUM_COUNTRIES = 3
MAX_REVISION = 2

PORT = 8000
HOST = "0.0.0.0"
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8000").split(",")

# crash at startup if any required key is absent rather than failing mid-request
_missing = [k for k, v in {"GROQ_API_KEY": GROQ_API_KEY, "TAVILY_API_KEY": TAVILY_API_KEY, "EXA_API_KEY": EXA_API_KEY}.items() if not v]
if _missing:
    sys.exit(f"[FATAL] Missing required environment variables: {', '.join(_missing)}")
