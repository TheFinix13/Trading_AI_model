# syntax=docker/dockerfile:1.6
#
# Image for the EURUSD AI agent dashboard. Single service: FastAPI app
# (`agent.dashboard.app:app`) on port 8000. Backtests + scorer training
# are out of scope -- run those on the host or in a different image.
#
#   docker build -t eurusd-ai-agent .
#   docker compose up
#
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY agent ./agent
COPY config ./config
COPY scripts ./scripts

RUN pip install --upgrade pip \
    && pip install -e .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent --max-time 4 http://localhost:8000/ || exit 1

CMD ["uvicorn", "agent.dashboard.app:app", "--host", "0.0.0.0", "--port", "8000"]
