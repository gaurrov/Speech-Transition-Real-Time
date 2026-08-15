"""
Central language registry for translation.

Every provider resolves its provider-specific codes here; pipeline code never
branches on language pairs. Each language carries:

* ``iso_code`` -- the canonical code used across the app (BCP-47 style: "en").
* ``display_name`` -- human-readable name.
* ``cloud_code`` -- provider-specific code; defaults to ``iso_code`` when unset.
* ``nllb_code`` -- NLLB-200 FLORES-200 language token (e.g. "hin_Deva").

The registry is data, not conditionals: adding or editing an entry is all it
takes to make a language available to both cloud and NLLB providers. Extra
languages can be registered at runtime via ``register_language()`` or the
``TRANSLATION_EXTRA_LANGUAGES`` setting (consumed by the provider factory).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.translation.base import TranslationError


@dataclass(frozen=True)
class Language:
    iso_code: str
    display_name: str
    cloud_code: str | None = None  # defaults to iso_code when None
    nllb_code: str | None = None  # NLLB-200 FLORES-200 token; None = not supported offline


LANGUAGES: tuple[Language, ...] = (
    Language("en", "English", nllb_code="eng_Latn"),
    Language("hi", "Hindi", nllb_code="hin_Deva"),
    Language("ta", "Tamil", nllb_code="tam_Taml"),
    Language("te", "Telugu", nllb_code="tel_Telu"),
    Language("ml", "Malayalam", nllb_code="mal_Mlym"),
    Language("kn", "Kannada", nllb_code="kan_Knda"),
    Language("es", "Spanish", nllb_code="spa_Latn"),
    Language("fr", "French", nllb_code="fra_Latn"),
    Language("de", "German", nllb_code="deu_Latn"),
    Language("pt", "Portuguese", nllb_code="por_Latn"),
    Language("ja", "Japanese", nllb_code="jpn_Jpan"),
    Language("ko", "Korean", nllb_code="kor_Hang"),
    Language("zh", "Chinese", nllb_code="zho_Hans"),
    Language("ar", "Arabic", nllb_code="arb_Arab"),
    Language("ru", "Russian", nllb_code="rus_Cyrl"),
)

_REGISTRY: dict[str, Language] = {lang.iso_code: lang for lang in LANGUAGES}


def register_language(language: Language) -> None:
    """Add or replace a language at runtime (idempotent per ``iso_code``)."""
    _REGISTRY[language.iso_code] = language


def apply_extra_languages(entries: list[dict] | None) -> None:
    """Register extra languages from the ``TRANSLATION_EXTRA_LANGUAGES`` setting.

    Each entry may carry ``iso_code`` (required), ``display_name``,
    ``cloud_code``, and ``nllb_code``.
    """
    for entry in entries or []:
        register_language(
            Language(
                iso_code=entry["iso_code"],
                display_name=entry.get("display_name", entry["iso_code"]),
                cloud_code=entry.get("cloud_code"),
                nllb_code=entry.get("nllb_code"),
            )
        )


def get_language(code: str) -> Language:
    language = _REGISTRY.get(code)
    if language is None:
        raise TranslationError("unsupported_language", f"Unsupported language: {code!r}")
    return language


def is_supported(code: str) -> bool:
    """True for "auto" or any registered language code."""
    return code == "auto" or code in _REGISTRY


def cloud_code(code: str) -> str:
    """Provider-specific language code for the cloud translation API.

    ``"auto"`` maps to ``"auto"``: the cloud API performs language detection
    when the source is omitted, so the provider can pass it straight through.
    """
    if code == "auto":
        return "auto"
    language = get_language(code)
    return language.cloud_code or language.iso_code


def nllb_code(code: str) -> str:
    """NLLB-200 FLORES-200 token for a language, or an error if unsupported.

    Offline NLLB has no language detection, so ``"auto"`` is rejected here.
    """
    if code == "auto":
        raise TranslationError(
            "unsupported_language",
            "Auto-detect is not supported by the offline NLLB provider; a concrete source language is required",
        )
    language = get_language(code)
    if language.nllb_code is None:
        raise TranslationError(
            "unsupported_language", f"No NLLB mapping for language: {code!r}"
        )
    return language.nllb_code
