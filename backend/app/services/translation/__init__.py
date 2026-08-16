"""Translation provider registry. Only the abstraction is imported here."""
from __future__ import annotations

import importlib.util

import structlog

from app.config import Settings, get_settings
from app.services.translation.base import TranslationError, TranslationProvider
from app.services.translation.languages import apply_extra_languages

__all__ = [
    "TranslationError",
    "TranslationProvider",
    "create_translation_provider",
    "warn_on_translation_misconfiguration",
]

logger = structlog.get_logger(__name__)


def _offline_runtime_available() -> bool:
    """True when the NLLB offline runtime (torch + transformers) is installed.

    Uses ``find_spec`` so the check stays cheap and never imports the heavy
    packages at startup.
    """
    return (
        importlib.util.find_spec("torch") is not None
        and importlib.util.find_spec("transformers") is not None
    )


def warn_on_translation_misconfiguration(settings: Settings) -> None:
    """Log a clear one-time warning when the effective translation path is dead.

    A fresh install ships with ``translation_provider="hybrid"`` and no cloud
    API key, so every utterance fails (cloud -> NLLB fallback -> both error).
    Surfacing that up-front beats a per-utterance ``translation_failed``.
    """
    cloud_configured = bool(settings.cloud_translation_api_key)
    offline_available = _offline_runtime_available()

    if settings.translation_provider == "cloud":
        if not cloud_configured:
            logger.warning(
                "translation_misconfigured",
                translation_provider="cloud",
                message=(
                    "Cloud translation is pinned but CLOUD_TRANSLATION_API_KEY is not "
                    "set -- every translation attempt will fail. Set the key in "
                    ".env, or switch TRANSLATION_PROVIDER to a working backend."
                ),
            )
        return

    if settings.translation_provider == "nllb":
        if not offline_available:
            logger.warning(
                "translation_misconfigured",
                translation_provider="nllb",
                message=(
                    "NLLB translation is pinned but the offline runtime is not "
                    "installed -- install it with `uv sync --extra offline`, otherwise "
                    "every translation attempt will fail."
                ),
            )
        return

    # hybrid
    if not cloud_configured and not offline_available:
        logger.warning(
            "translation_misconfigured",
            translation_provider="hybrid",
            message=(
                "No cloud translation key (CLOUD_TRANSLATION_API_KEY) and the NLLB "
                "offline runtime is not installed -- every translation attempt will "
                "fail. Set the key in .env, install the offline extra with "
                "`uv sync --extra offline`, or both."
            ),
        )


def create_translation_provider() -> TranslationProvider:
    """Instantiate the translation provider selected by configuration.

    ``hybrid`` (default) composes the low-latency cloud provider with the
    NLLB-200 offline fallback. The transport layer calls this instead of
    importing a concrete provider, so vendor-specific code never leaks into
    the pipeline.
    """
    settings = get_settings()
    apply_extra_languages(settings.translation_extra_languages)

    if settings.translation_provider == "hybrid":
        from app.services.translation.hybrid_provider import HybridTranslationProvider

        return HybridTranslationProvider(settings=settings)
    if settings.translation_provider == "cloud":
        from app.services.translation.cloud_provider import CloudTranslationProvider

        return CloudTranslationProvider(settings=settings)
    if settings.translation_provider == "nllb":
        from app.services.translation.nllb_provider import NLLBTranslationProvider

        return NLLBTranslationProvider(settings=settings)
    raise TranslationError(
        "translation_config",
        f"Unknown translation provider configured: {settings.translation_provider!r}",
    )
