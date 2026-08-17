"""Translation provider registry. Only the abstraction is imported here."""
from __future__ import annotations

import importlib.util
import time

import structlog

from app.config import Settings, get_settings
from app.services.translation.base import TranslationError, TranslationProvider
from app.services.translation.languages import apply_extra_languages

__all__ = [
    "TranslationError",
    "TranslationProvider",
    "create_translation_provider",
    "is_translation_available",
    "warn_on_translation_misconfiguration",
]

logger = structlog.get_logger(__name__)

# Cache for NLLB service probe result to avoid hammering the service.
_nllb_service_reachable: bool | None = None
_nllb_probe_ts: float = 0.0
_NLLB_PROBE_TTL_SECONDS: float = 30.0


def _offline_runtime_available() -> bool:
    """True when the NLLB offline runtime (torch + transformers) is installed.

    Uses ``find_spec`` so the check stays cheap and never imports the heavy
    packages at startup.
    """
    return (
        importlib.util.find_spec("torch") is not None
        and importlib.util.find_spec("transformers") is not None
    )


def _nllb_fallback_available(settings: Settings) -> bool:
    """True when the NLLB fallback path can be used synchronously.

    In production the fallback is usually a separate NLLB service
    (``nllb_service_url``); on dev machines it can be the in-process model
    (``offline`` extra). Either one counts as "available".
    """
    return bool(settings.nllb_service_url) or _offline_runtime_available()


def _make_nllb_provider(settings: Settings) -> TranslationProvider:
    """Build the NLLB fallback provider: remote service or in-process."""
    if settings.nllb_service_url:
        from app.services.translation.nllb_service_provider import (
            NLLBServiceProvider,
        )

        return NLLBServiceProvider(settings=settings)
    from app.services.translation.nllb_provider import NLLBTranslationProvider

    return NLLBTranslationProvider(settings=settings)


async def probe_nllb_service() -> bool:
    """Async probe of the NLLB service. Result is cached for 30 seconds."""
    global _nllb_service_reachable, _nllb_probe_ts

    now = time.monotonic()
    if (
        _nllb_service_reachable is not None
        and (now - _nllb_probe_ts) < _NLLB_PROBE_TTL_SECONDS
    ):
        return _nllb_service_reachable

    settings = get_settings()
    if not settings.nllb_service_url:
        _nllb_service_reachable = _offline_runtime_available()
        _nllb_probe_ts = now
        return _nllb_service_reachable

    from app.services.translation.nllb_service_provider import (
        NLLBServiceProvider,
    )

    provider = NLLBServiceProvider(settings=settings)
    try:
        _nllb_service_reachable = await provider.health_check()
    except Exception:
        _nllb_service_reachable = False
    finally:
        _nllb_probe_ts = now
        await provider.close()
    return _nllb_service_reachable


async def is_translation_available(settings: Settings) -> bool:
    """Determine whether translations can actually be served right now.

    Unlike config-presence checks, this probes live backends (NLLB service
    health, cloud API key presence) to answer the real question: "will the
    next translation attempt succeed?"
    """
    if settings.translation_provider in ("hybrid", "cloud"):
        if settings.cloud_translation_api_key:
            return True
        if settings.translation_provider == "cloud":
            return False

    # nllb or hybrid fallback path
    if settings.nllb_service_url:
        from app.services.translation.nllb_service_provider import (
            NLLBServiceProvider,
        )

        provider = NLLBServiceProvider(settings=settings)
        try:
            return await provider.health_check()
        finally:
            await provider.close()

    return _offline_runtime_available()


def warn_on_translation_misconfiguration(settings: Settings) -> None:
    """Log a clear one-time warning when the effective translation path is dead.

    A fresh install ships with ``translation_provider="nllb"`` backed by the
    NLLB service. This surfaces a warning when that service is unreachable or
    when a misconfigured cloud/hybrid path has no working backend.
    """
    cloud_configured = bool(settings.cloud_translation_api_key)
    nllb_available = _nllb_fallback_available(settings)

    if settings.translation_provider == "cloud":
        if not cloud_configured:
            logger.warning(
                "translation_misconfigured",
                translation_provider="cloud",
                message=(
                    "Cloud translation is pinned but TRANSLATION_API_KEY is not "
                    "set -- every translation attempt will fail. Set the key in "
                    ".env, or switch TRANSLATION_PROVIDER to a working backend."
                ),
            )
        return

    if settings.translation_provider == "nllb":
        if not nllb_available:
            logger.warning(
                "translation_misconfigured",
                translation_provider="nllb",
                message=(
                    "NLLB translation is pinned but no fallback backend is "
                    "available -- set NLLB_SERVICE_URL to a running NLLB service, "
                    "or install the `offline` extra with `uv sync --extra offline`."
                ),
            )
        return

    # hybrid
    if not cloud_configured and not nllb_available:
        logger.warning(
            "translation_misconfigured",
            translation_provider="hybrid",
            message=(
                "No cloud translation key (TRANSLATION_API_KEY) and no NLLB "
                "fallback (set NLLB_SERVICE_URL or install the `offline` extra) "
                "-- every translation attempt will fail."
            ),
        )


def create_translation_provider() -> TranslationProvider:
    """Instantiate the translation provider selected by configuration.

    ``nllb`` (default) uses the NLLB-200 translation service. ``hybrid``
    composes the low-latency cloud provider with NLLB-200 as a fallback.
    ``cloud`` pins the cloud provider alone. The transport layer calls this
    instead of importing a concrete provider, so vendor-specific code never
    leaks into the pipeline.
    """
    settings = get_settings()
    apply_extra_languages(settings.translation_extra_languages)

    if settings.translation_provider == "hybrid":
        from app.services.translation.hybrid_provider import HybridTranslationProvider

        cloud = None
        if settings.cloud_translation_api_key:
            from app.services.translation.cloud_provider import CloudTranslationProvider

            cloud = CloudTranslationProvider(settings=settings)

        return HybridTranslationProvider(
            settings=settings,
            cloud=cloud,
            nllb=_make_nllb_provider(settings),
        )
    if settings.translation_provider == "cloud":
        from app.services.translation.cloud_provider import CloudTranslationProvider

        return CloudTranslationProvider(settings=settings)
    if settings.translation_provider == "nllb":
        return _make_nllb_provider(settings)
    raise TranslationError(
        "translation_config",
        f"Unknown translation provider configured: {settings.translation_provider!r}",
    )
