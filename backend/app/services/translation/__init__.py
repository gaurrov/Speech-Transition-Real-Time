"""Translation provider registry. Only the abstraction is imported here."""
from __future__ import annotations

from app.config import get_settings
from app.services.translation.base import TranslationError, TranslationProvider
from app.services.translation.languages import apply_extra_languages

__all__ = [
    "TranslationError",
    "TranslationProvider",
    "create_translation_provider",
]


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
