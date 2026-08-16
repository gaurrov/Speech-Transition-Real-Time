# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Builder stage: resolve dependencies with uv (no runtime tooling included).
# Only the locked production dependencies are installed -- the `dev` group and
# the heavy `offline` (torch/transformers) extra are intentionally excluded.
# NLLB-200 runs as a separate service (see ../nllb) in production.
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Install dependencies first for layer caching; the app source is copied later.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

# ---------------------------------------------------------------------------
# Runtime stage: slim base image, non-root user, production ASGI server.
# ---------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    WORKDIR_SRC="/app"

WORKDIR /app

# Non-root runtime user. All secrets arrive at runtime via environment, never
# baked into the image.
RUN groupadd --system app && useradd --system --gid app app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app app ./app
COPY --chown=app:app docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

USER app

EXPOSE 8000

# Health probe using the Python stdlib (no curl needed in the slim image).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

ENTRYPOINT ["./docker-entrypoint.sh"]
