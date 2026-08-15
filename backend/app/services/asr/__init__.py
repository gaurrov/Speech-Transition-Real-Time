"""ASR provider registry. Only the abstraction is imported here."""
from __future__ import annotations

from app.config import get_settings
from app.services.asr.base import ASRProvider, ASRProviderError

__all__ = ["ASRProvider", "ASRProviderError", "create_asr_provider"]


def create_asr_provider() -> ASRProvider:
    """Instantiate the ASR provider selected by configuration.

    The transport layer calls this instead of importing a concrete provider,
    so Deepgram-specific code never leaks into the pipeline.
    """
    settings = get_settings()
    if settings.asr_provider == "deepgram":
        from app.services.asr.deepgram_provider import DeepgramASRProvider

        return DeepgramASRProvider()
    raise ASRProviderError(
        "asr_config", f"Unknown ASR provider configured: {settings.asr_provider!r}"
    )
