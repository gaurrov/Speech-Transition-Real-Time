"""Tests for the central language registry."""
import pytest

from app.services.translation import languages
from app.services.translation.base import TranslationError
from app.services.translation.languages import (
    LANGUAGES,
    Language,
    apply_extra_languages,
    cloud_code,
    detect_language,
    get_language,
    is_supported,
    nllb_code,
    register_language,
)


def test_builtin_languages_are_known() -> None:
    codes = {lang.iso_code for lang in LANGUAGES}
    assert {"en", "hi", "ta", "es", "fr", "ja", "zh", "ar"} <= codes


def test_display_names() -> None:
    assert get_language("en").display_name == "English"
    assert get_language("hi").display_name == "Hindi"
    assert get_language("ta").display_name == "Tamil"


def test_nllb_flores_codes() -> None:
    assert nllb_code("en") == "eng_Latn"
    assert nllb_code("hi") == "hin_Deva"
    assert nllb_code("ta") == "tam_Taml"
    assert nllb_code("te") == "tel_Telu"
    assert nllb_code("ml") == "mal_Mlym"
    assert nllb_code("kn") == "kan_Knda"
    assert nllb_code("es") == "spa_Latn"
    assert nllb_code("fr") == "fra_Latn"
    assert nllb_code("de") == "deu_Latn"
    assert nllb_code("pt") == "por_Latn"
    assert nllb_code("ja") == "jpn_Jpan"
    assert nllb_code("ko") == "kor_Hang"
    assert nllb_code("zh") == "zho_Hans"
    assert nllb_code("ar") == "arb_Arab"
    assert nllb_code("ru") == "rus_Cyrl"


def test_cloud_code_defaults_to_iso() -> None:
    assert cloud_code("en") == "en"
    assert cloud_code("hi") == "hi"


def test_cloud_code_auto_is_passthrough() -> None:
    assert cloud_code("auto") == "auto"


def test_nllb_code_auto_is_rejected() -> None:
    with pytest.raises(TranslationError) as exc:
        nllb_code("auto")
    assert exc.value.code == "unsupported_language"


def test_unknown_language_raises_unsupported() -> None:
    with pytest.raises(TranslationError) as exc:
        get_language("xx")
    assert exc.value.code == "unsupported_language"
    with pytest.raises(TranslationError) as exc:
        nllb_code("xx")
    assert exc.value.code == "unsupported_language"


def test_is_supported() -> None:
    assert is_supported("hi")
    assert is_supported("auto")
    assert not is_supported("xx")


def test_register_language_adds_mapping() -> None:
    try:
        register_language(Language("ur", "Urdu", nllb_code="urd_Arab"))
        assert is_supported("ur")
        assert get_language("ur").display_name == "Urdu"
        assert nllb_code("ur") == "urd_Arab"
        assert cloud_code("ur") == "ur"
    finally:
        languages._REGISTRY.pop("ur", None)


def test_register_language_overrides() -> None:
    try:
        register_language(Language("en", "English", cloud_code="en-US", nllb_code="eng_Latn"))
        assert get_language("en").display_name == "English"
        assert cloud_code("en") == "en-US"
    finally:
        register_language(Language("en", "English", nllb_code="eng_Latn"))


def test_apply_extra_languages() -> None:
    apply_extra_languages(
        [{"iso_code": "mr", "display_name": "Marathi", "nllb_code": "mar_Deva"}]
    )
    try:
        assert is_supported("mr")
        assert nllb_code("mr") == "mar_Deva"
        assert cloud_code("mr") == "mr"
    finally:
        languages._REGISTRY.pop("mr", None)


def test_apply_extra_languages_none_is_noop() -> None:
    apply_extra_languages(None)
    assert is_supported("en")


# --- detect_language ---------------------------------------------------------


def test_detect_language_latin_defaults_to_english() -> None:
    assert detect_language("Hello world") == "en"
    assert detect_language("Bonjour le monde") == "en"  # Latin script → "en"


def test_detect_language_hindi() -> None:
    assert detect_language("नमस्ते दुनिया") == "hi"


def test_detect_language_tamil() -> None:
    assert detect_language("வணக்கம் உலகம்") == "ta"


def test_detect_language_telugu() -> None:
    assert detect_language("హలో ప్రపంచం") == "te"


def test_detect_language_kannada() -> None:
    assert detect_language("ಹಲೋ ಜಗತ್ತು") == "kn"


def test_detect_language_malayalam() -> None:
    assert detect_language("ഹലോ ലോകം") == "ml"


def test_detect_language_japanese() -> None:
    assert detect_language("こんにちは世界") == "ja"  # Hiragana
    assert detect_language("カタカナテスト") == "ja"  # Katakana


def test_detect_language_korean() -> None:
    assert detect_language("안녕하세요 세계") == "ko"


def test_detect_language_chinese() -> None:
    assert detect_language("你好世界") == "zh"


def test_detect_language_arabic() -> None:
    assert detect_language("مرحبا بالعالم") == "ar"


def test_detect_language_russian() -> None:
    assert detect_language("Привет мир") == "ru"


def test_detect_language_empty_string() -> None:
    assert detect_language("") == "en"


def test_detect_language_whitespace_only() -> None:
    assert detect_language("   ") == "en"


def test_detect_language_numbers_and_punctuation() -> None:
    assert detect_language("123 !@#") == "en"


def test_detect_language_mixed_scripts_picks_dominant() -> None:
    # Predominantly Hindi with some English
    text = "नमस्ते this is a test दुनिया में आपका स्वागत है"
    assert detect_language(text) == "hi"
