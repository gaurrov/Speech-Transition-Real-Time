# syntax=docker/dockerfile:1

# Internal-only NLLB-200 translation service. This image is intentionally
# never published to a public port; the main backend reaches it over the
# Docker network via NLLB_SERVICE_URL.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models \
    HF_HUB_ENABLE_HF_TRANSFER=0

WORKDIR /app

# torch first from the CPU-only wheel index (saves ~1 GB of CUDA libs).
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.2"

# Everything else (fastapi, transformers, sentencepiece, ...) from PyPI.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

# Non-root runtime user. The model cache lives at /models (an app-owned
# volume) so the non-root user can download and cache model weights.
RUN mkdir -p /models && \
    groupadd --system app && useradd --system --gid app app && \
    chown -R app:app /models /app
USER app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
