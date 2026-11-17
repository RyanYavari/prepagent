# PrepAgent API. Build from backend/:  docker build -t prepagent-api:<tag> .
# Single worker on purpose: OAuth PKCE verifiers and rate limits live in process memory
# (specs/deployment.md). Never add --workers > 1 or --reload.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --system --uid 10001 --no-create-home app

WORKDIR /app

COPY requirements-runtime.txt .
RUN pip install -r requirements-runtime.txt

# .dockerignore keeps .env files, tests, evals and caches out of this copy.
COPY --chown=app:app . .

USER app
EXPOSE 8000

# /health is static (no Supabase or LLM call), so checking it costs nothing.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).status == 200 else 1)"]

# --forwarded-allow-ips=* is safe only because port 8000 is reachable solely from the
# Caddy container on the compose network; never publish it on the host.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
