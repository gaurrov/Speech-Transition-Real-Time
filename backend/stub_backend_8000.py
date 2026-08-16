"""Disposable server for full-stack system-audio E2E: real FastAPI app on
port 8000 with scripted ASR/translation/LLM providers (from soak_ws.py).
"""
from __future__ import annotations

import os

os.environ.setdefault("SOAK_PORT", "8000")

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402
from soak_ws import _install_fakes  # noqa: E402

_install_fakes()
uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
