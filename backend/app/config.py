"""
Centralized application configuration.

All runtime configuration is sourced from environment variables (see
`.env.example` at the repository root). Nothing here should hardcode
provider-specific secrets or endpoints -- that keeps `Settings` safe to
import from anywhere in the app, including tests.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General ---
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- ASR (Automatic Speech Recognition) ---
    asr_provider: Literal["deepgram"] = "deepgram"
    deepgram_api_key: str | None = None
    deepgram_model: str = "nova-2"
    # Base websocket endpoint for streaming listen (override for tests / proxies).
    deepgram_endpoint: str = "wss://api.deepgram.com/v1/listen"
    deepgram_interim_results: bool = True
    deepgram_endpointing_ms: int = 600  # silence (ms) after which Deepgram finalizes an utterance
    deepgram_utterance_end_ms: int = 900  # utterance_end marker (>= endpointing)
    deepgram_punctuate: bool = True
    deepgram_smart_format: bool = True
    deepgram_language_detection: bool = True  # used when source_language == "auto"
    deepgram_connect_timeout_sec: float = 10.0
    deepgram_send_timeout_sec: float = 5.0
    deepgram_reconnect_max_attempts: int = 3
    deepgram_reconnect_base_delay_ms: int = 500
    deepgram_audio_buffer_seconds: float = 2.0  # in-flight audio kept across reconnects

    # --- Translation ---
    # "cloud" is the default low-latency path; "nllb" is the offline/fallback path.
    translation_provider: Literal["cloud", "nllb"] = "cloud"
    cloud_translation_api_key: str | None = None
    cloud_translation_provider_name: Literal["google", "deepl", "azure"] = "google"
    nllb_model_name: str = "facebook/nllb-200-distilled-600M"
    nllb_device: Literal["cpu", "cuda"] = "cpu"

    # --- LLM (async post-processing / refinement) ---
    llm_refinement_enabled: bool = True
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    llm_api_key: str | None = None
    llm_model: str = "claude-sonnet-4-6"

    # --- VAD (server-side awareness of client-side Silero VAD events) ---
    silence_finalize_ms: int = 700  # silence duration that finalizes an utterance
    silence_min_speech_ms: int = 150  # minimum speech duration to avoid noise triggers

    # --- WebSocket / audio ---
    audio_sample_rate: int = 16_000
    audio_encoding: Literal["linear16", "opus"] = "linear16"
    max_ws_message_bytes: int = 1_000_000


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor; import this instead of instantiating Settings() directly."""
    return Settings()
