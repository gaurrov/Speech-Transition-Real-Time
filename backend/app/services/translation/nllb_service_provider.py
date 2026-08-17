"""
NLLBServiceProvider: NLLB-200 fallback served by a separate internal service.

In production the heavy torch + transformers runtime stays out of the main
backend container. Instead, a dedicated ``nllb`` service (see the ``nllb/``
directory) loads NLLB-200 once and exposes a tiny internal HTTP API. This
provider is the backend's HTTP client for that service.

Selected automatically by the translation factory whenever
``nllb_service_url`` is set (``TRANSLATION_PROVIDER=hybrid|nllb``). When the
URL is unset the factory falls back to the in-process
``NLLBTranslationProvider`` (dev machines with the ``offline`` extra).

Failure codes (all ``TranslationError``):
  * ``nllb_service_connection`` -- HTTP transport error (service down).
  * ``nllb_service_error``       -- HTTP >= 400 or malformed response body.

The provider keeps ``name = "nllb"`` so the client-side "provider" label and
the hybrid fallback logic stay identical whether NLLB runs in-process or in a
sidecar container.
"""
from __future__ import annotations

import httpx
import structlog

from app.config import Settings, get_settings
from app.models.schemas import TranslationSegment
from app.services.translation.base import TranslationError, TranslationProvider
from app.services.translation.languages import nllb_code

logger = structlog.get_logger(__name__)


class NLLBServiceProvider(TranslationProvider):
    name = "nllb"

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or httpx.AsyncClient(
            timeout=self._settings.nllb_service_timeout_sec
        )
        self._base_url = (self._settings.nllb_service_url or "").rstrip("/")

    async def translate(
        self,
        *,
        segment_id: str,
        text: str,
        source_language: str,
        target_language: str,
        is_final: bool,
    ) -> TranslationSegment:
        if not self._base_url:
            raise TranslationError(
                "nllb_service_config", "NLLB_SERVICE_URL is not configured"
            )
        # Resolve codes first so an unsupported language fails fast and clearly
        # (mirrors the in-process provider; NLLB has no language detection).
        if source_language == "auto":
            raise TranslationError(
                "unsupported_language",
                "NLLB does not support auto-detect; configure a concrete "
                "source language or use a cloud/hybrid provider with an API key",
            )
        nllb_code(source_language)
        nllb_code(target_language)

        if not text.strip():
            return TranslationSegment(
                segment_id=segment_id,
                source_text=text,
                translated_text="",
                source_language=source_language,
                target_language=target_language,
                is_final=is_final,
                provider=self.name,
            )

        payload = {
            "text": text,
            "source_lang": nllb_code(source_language),
            "target_lang": nllb_code(target_language),
        }
        try:
            response = await self._client.post(
                f"{self._base_url}/translate", json=payload
            )
        except httpx.HTTPError as exc:
            raise TranslationError(
                "nllb_service_connection",
                f"NLLB service unreachable: {exc}",
            ) from exc

        if response.status_code >= 400:
            detail = response.text[:200]
            raise TranslationError(
                "nllb_service_error",
                f"NLLB service error (HTTP {response.status_code}): {detail}",
            )

        try:
            body = response.json()
            translated = body["translated_text"]
        except (KeyError, ValueError) as exc:
            raise TranslationError(
                "nllb_service_error",
                "NLLB service returned an unexpected response",
            ) from exc

        return TranslationSegment(
            segment_id=segment_id,
            source_text=text,
            translated_text=translated,
            source_language=source_language,
            target_language=target_language,
            is_final=is_final,
            provider=self.name,
        )

    async def health_check(self) -> bool:
        if not self._base_url:
            return False
        try:
            response = await self._client.get(
                f"{self._base_url}/health", timeout=2.0
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._client.aclose()
