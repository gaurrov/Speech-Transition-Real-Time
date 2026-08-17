"""Configuration defaults tests."""
import os

from app.config import Settings


def test_defaults_are_sane() -> None:
    settings = Settings()
    assert settings.asr_provider == "deepgram"
    assert settings.translation_provider == "nllb"
    assert settings.nllb_model_name == "facebook/nllb-200-distilled-600M"
    assert settings.cloud_translation_provider_name == "google"
    assert settings.cloud_translation_timeout_sec == 5.0
    assert settings.nllb_max_length == 128
    assert settings.nllb_num_beams == 4
    assert settings.llm_refinement_enabled is True
    assert settings.audio_sample_rate == 16_000
    assert settings.cors_allow_origins == ["http://localhost:5173"]
    assert settings.log_format == "console"
    assert settings.nllb_service_url is None
    assert settings.ws_allowed_origins is None


def test_environment_alias_maps_to_app_env() -> None:
    os.environ["ENVIRONMENT"] = "production"
    try:
        settings = Settings()
        assert settings.app_env == "production"
    finally:
        del os.environ["ENVIRONMENT"]


def test_translation_api_key_alias_maps_to_cloud_key() -> None:
    os.environ["TRANSLATION_API_KEY"] = "sk-translate"
    try:
        settings = Settings()
        assert settings.cloud_translation_api_key == "sk-translate"
    finally:
        del os.environ["TRANSLATION_API_KEY"]


def test_nllb_service_url_setting() -> None:
    os.environ["NLLB_SERVICE_URL"] = "http://nllb:8000"
    try:
        settings = Settings()
        assert settings.nllb_service_url == "http://nllb:8000"
    finally:
        del os.environ["NLLB_SERVICE_URL"]
