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

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- General ---
    # Accepts both ENVIRONMENT (preferred) and the older APP_ENV spelling.
    app_env: Literal["development", "staging", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "APP_ENV"),
    )
    log_level: str = "INFO"
    # "console" = pretty dev rendering, "json" = structured JSON lines (prod).
    log_format: Literal["console", "json"] = "console"
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    # Optional WebSocket Origin allowlist (cross-site WebSocket hijacking
    # protection). When set to a non-empty list, /ws/translate rejects
    # handshakes whose Origin header is not listed. Leave empty to allow any
    # Origin (required for the Electron file:// client unless you list it).
    ws_allowed_origins: list[str] | None = None

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
    # "hybrid" (default) tries the low-latency cloud provider first and falls
    # back to NLLB-200 offline; "cloud"/"nllb" pin a single path.
    translation_provider: Literal["hybrid", "cloud", "nllb"] = "hybrid"
    # Accepts either TRANSLATION_API_KEY (preferred) or the older
    # CLOUD_TRANSLATION_API_KEY spelling.
    cloud_translation_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TRANSLATION_API_KEY", "CLOUD_TRANSLATION_API_KEY"
        ),
    )
    cloud_translation_provider_name: Literal["google", "deepl", "azure"] = "google"
    # Google Cloud Translation v2 REST endpoint. Override for tests / proxies.
    cloud_translation_endpoint: str = "https://translation.googleapis.com/language/translate/v2"
    cloud_translation_timeout_sec: float = 5.0
    # Extra languages registered into the central language registry at startup,
    # e.g. [{"iso_code":"mr","display_name":"Marathi","nllb_code":"mar_Deva"}].
    translation_extra_languages: list[dict] | None = None
    nllb_model_name: str = "facebook/nllb-200-distilled-600M"
    nllb_device: Literal["cpu", "cuda"] = "cpu"
    nllb_max_length: int = 128
    nllb_num_beams: int = 4
    # When set, the NLLB fallback is served by a separate, internal NLLB
    # service over HTTP instead of loading torch in-process (keeps the main
    # backend image small). The service is never exposed publicly.
    nllb_service_url: str | None = None
    nllb_service_timeout_sec: float = 30.0

    # --- LLM (async post-processing / refinement) ---
    # Accepts either ENABLE_LLM_REFINEMENT (preferred) or the older
    # LLM_REFINEMENT_ENABLED spelling.
    llm_refinement_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "ENABLE_LLM_REFINEMENT", "LLM_REFINEMENT_ENABLED"
        ),
    )
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    llm_api_key: str | None = None
    llm_model: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 256
    # How long one refinement call may take before it is abandoned. Refinement
    # is off the hot path, so this is generous but still bounded.
    llm_timeout_sec: float = 20.0
    # How many preceding finalized segments are passed as context so
    # terminology stays consistent across an utterance/meeting.
    llm_context_segments: int = 4
    # Override for proxies/tests; defaults to the provider's public endpoint.
    llm_endpoint: str | None = None
    # Skip an LLM refinement call entirely when the finalized transcript
    # already looks clean (proper punctuation, capitalization, no duplicate
    # words). Saves an unnecessary round-trip per well-formed utterance.
    llm_skip_when_clean: bool = True

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
