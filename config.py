# config.py
import os
from dotenv import load_dotenv

load_dotenv(override=True)

# API Keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
EXA_API_KEY = os.getenv("EXA_API_KEY")

# Model Settings
MAIN_MODEL_NAME = "meta-llama/llama-4-scout-17b-16e-instruct"
FALLBACK_MODEL_NAME = "meta-llama/llama-4-scout-17b-16e-instruct"
ROUTER_MODEL_NAME = "meta-llama/llama-4-scout-17b-16e-instruct"
TEMPERATURE = 0.0

# Chat settings
NUM_COUNTRIES = 3
MAX_REVISION = 2

# Server Settings
PORT = 8000
HOST = "0.0.0.0"