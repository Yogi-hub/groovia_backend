# Slim production image for the FastAPI + LangGraph backend.
# Targets Linux/amd64 — Render's runtime.
FROM python:3.13-slim AS runtime

# System deps:
#   - build-essential: only needed if a wheel build is required during pip install
#   - curl: for the HEALTHCHECK
# After install, drop build-essential to keep the image small.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/*

# Run as a non-root user — required by Render's security model.
RUN useradd --create-home --shell /bin/bash app
WORKDIR /app

# Install Python deps first to cache the layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && apt-get purge -y build-essential \
 && apt-get autoremove -y

# Copy only what the running app needs. Tests, migrations and dev scripts excluded by .dockerignore.
COPY --chown=app:app \
     main.py backend.py config.py content.py prompts.py schema.py utils.py db.py auth.py rate_limit.py nylas_client.py \
     ./
COPY --chown=app:app routers ./routers

USER app

# Render injects PORT at runtime. uvicorn binds to it; falls back to 8000 locally.
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -fsS "http://localhost:${PORT:-8000}/health" || exit 1

CMD ["sh", "-c", "uvicorn main:api --host 0.0.0.0 --port ${PORT:-8000}"]
