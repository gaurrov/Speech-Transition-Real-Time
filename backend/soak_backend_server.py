"""Disposable: stub backend server for the Electron soak test.

Same scripted providers as soak_ws.py (chunk-count-driven ASR, echo
translation, tiny LLM) but as a long-running server on the app's default port
so the real Electron renderer can be exercised end-to-end. Real microphone
audio flows in; finals are emitted on a chunk cadence, so translations stream
continuously even in silence.
"""
from __future__ import annotations

import os

import uvicorn

from app.main import app
from app.websocket import translate_stream
from soak_ws import SoakASR, SoakLLM, SoakTranslator


def main() -> None:
    translate_stream.create_asr_provider = lambda: SoakASR()
    translate_stream.create_translation_provider = lambda: SoakTranslator()
    translate_stream.create_llm_provider = lambda: SoakLLM()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("SOAK_PORT", "8000")),
        log_level="warning",
    )


if __name__ == "__main__":
    main()
