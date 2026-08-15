"""
CloudTranslationProvider: default low-latency translation path.

Talks to the Google Cloud Translation v2 REST API (``/language/translate/v2``)
directly with httpx -- no SDK, minimal footprint. The endpoint is
configurable (``cloud_translation_endpoint``) so proxies and tests can point
it elsewhere. On any failure it raises ``TranslationError`` so the hybrid
provider can fall back to NLLB; it never fails the whole session by itself.
"""
from __future__ import annotations

import httpx
import structlog

from app.config import Settings, get_settings
from app.models.schemas import TranslationSegment
from app.services.translation.base import TranslationError, TranslationProvider
from app.services.translation.languages import cloud_code

logger = structlog.get_logger(__name__)


class CloudTranslationProvider(TranslationProvider):
    name = "cloud"

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if self._settings.cloud_translation_provider_name != "google":
            raise TranslationError(
                "cloud_config",
                f"Only the Google-compatible translation API is wired; got "
                f"cloud_translation_provider_name={self._settings.cloud_translation_provider_name!r}",
            )
        self._client = client or httpx.AsyncClient(
            timeout=self._settings.cloud_translation_timeout_sec
        )

    async def translate(
        self,
        *,
        segment_id: str,
        text: str,
        source_language: str,
        target_language: str,
        is_final: bool,
    ) -> TranslationSegment:
        api_key = self._settings.cloud_translation_api_key
        if not api_key:
            raise TranslationError(
                "cloud_config", "Cloud translation API key is not configured"
            )
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

        params = {"key": api_key}
        payload: dict = {
            "q": text,
            "target": cloud_code(target_language),
            "format": "text",
        }
        source = cloud_code(source_language)
        if source != "auto":
            payload["source"] = source

        try:
            response = await self._client.post(
                self._settings.cloud_translation_endpoint,
                params=params,
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise TranslationError(
                "cloud_connection", f"Cloud translation request failed: {exc}"
            ) from exc

        if response.status_code >= 400:
            detail = response.text[:200]
            raise TranslationError(
                "cloud_translation_error",
                f"Cloud translation failed (HTTP {response.status_code}): {detail}",
            )

        try:
            body = response.json()
            translated = body["data"]["translations"][0]["translatedText"]
        except (KeyError, IndexError, ValueError) as exc:
            raise TranslationError(
                "cloud_translation_error",
                "Cloud translation returned an unexpected response",
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
        # Cheap check: no network round-trip, just whether credentials exist.
        return bool(self._settings.cloud_translation_api_key)

    async def close(self) -> None:
        await self._client.aclose()
