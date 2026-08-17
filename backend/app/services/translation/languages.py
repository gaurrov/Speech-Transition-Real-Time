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


# ---------------------------------------------------------------------------
# Lightweight language detection via Unicode character ranges.
# ---------------------------------------------------------------------------

# (start_codepoint, end_codepoint, iso_code) — order matters: more specific
# scripts are checked first (e.g. Japanese kana before generic CJK).
_SCRIPT_RANGES: list[tuple[int, int, str]] = [
    (0x3040, 0x309F, "ja"),  # Hiragana
    (0x30A0, 0x30FF, "ja"),  # Katakana
    (0xAC00, 0xD7AF, "ko"),  # Hangul Syllables
    (0x0900, 0x097F, "hi"),  # Devanagari
    (0x0B80, 0x0BFF, "ta"),  # Tamil
    (0x0C00, 0x0C7F, "te"),  # Telugu
    (0x0C80, 0x0CFF, "kn"),  # Kannada
    (0x0D00, 0x0D7F, "ml"),  # Malayalam
    (0x0600, 0x06FF, "ar"),  # Arabic
    (0x0400, 0x04FF, "ru"),  # Cyrillic
    (0x4E00, 0x9FFF, "zh"),  # CJK Unified Ideographs (Chinese/Japanese shared range)
]

# Minimum fraction of characters that must match a script for detection.
_DETECTION_THRESHOLD = 0.3


def detect_language(text: str) -> str:
    """Detect the language of *text* using Unicode script analysis.

    Returns an ISO 639-1 code (e.g. ``"en"``, ``"hi"``) suitable for
    ``nllb_code()`` or ``cloud_code()``.  Falls back to ``"en"`` when the
    text is too short or uses Latin script (which covers English, Spanish,
    French, German, and Portuguese — all Latin-script languages in the
    registry).

    This is a heuristic: it works well for the languages this app supports
    and requires zero external dependencies.  It is *not* suitable for
    disambiguating closely related scripts (e.g. Hindi vs. Marathi) — use a
    proper CLD3/CLD2 library for that.
    """
    if not text or not text.strip():
        return "en"

    total_alpha = 0
    script_counts: dict[str, int] = {}
    for ch in text:
        if not ch.isalpha():
            continue
        total_alpha += 1
        cp = ord(ch)
        for start, end, code in _SCRIPT_RANGES:
            if start <= cp <= end:
                script_counts[code] = script_counts.get(code, 0) + 1
                break

    if total_alpha == 0:
        return "en"

    # Find the dominant script.
    best_code = "en"
    best_count = 0
    for code, count in script_counts.items():
        if count > best_count:
            best_count = count
            best_code = code

    if best_count / total_alpha >= _DETECTION_THRESHOLD:
        return best_code

    return "en"
