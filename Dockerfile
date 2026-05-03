# Base image selection
FROM python:3.11-slim

# System dependency installation
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Working directory setup
WORKDIR /app

# Dependency management
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application source copy
COPY main.py backend.py config.py prompts.py schema.py utils.py requirements.txt ./

# Port exposure
EXPOSE ${PORT:-8000}

# Server execution — reads $PORT set by the platform (Render), falls back to 8000 locally
CMD sh -c "uvicorn main:api --host 0.0.0.0 --port ${PORT:-8000}"