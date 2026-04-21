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
COPY . .

# Port exposure
EXPOSE 8000

# Server execution
CMD ["uvicorn", "main:api", "--host", "0.0.0.0", "--port", "8000"]