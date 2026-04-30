# config.py
import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
EXA_API_KEY = os.getenv("EXA_API_KEY")

MAIN_MODEL_NAME = "llama-3.3-70b-versatile"
REVIEW_MODEL_NAME = "openai/gpt-oss-120b"
TEMPERATURE = 0.0

NUM_COUNTRIES = 4
MAX_REVISION = 3

PORT = 8000
HOST = "0.0.0.0"
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8501,http://localhost:8502,http://localhost:8503").split(",")

_missing = [k for k, v in {"GROQ_API_KEY": GROQ_API_KEY, "TAVILY_API_KEY": TAVILY_API_KEY, "EXA_API_KEY": EXA_API_KEY}.items() if not v]
if _missing:
    sys.exit(f"[FATAL] Missing required environment variables: {', '.join(_missing)}")
