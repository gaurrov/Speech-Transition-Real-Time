"""Configuration defaults tests."""
from app.config import Settings


def test_defaults_are_sane() -> None:
    settings = Settings()
    assert settings.asr_provider == "deepgram"
    assert settings.translation_provider == "hybrid"
    assert settings.nllb_model_name == "facebook/nllb-200-distilled-600M"
    assert settings.cloud_translation_provider_name == "google"
    assert settings.cloud_translation_timeout_sec == 5.0
    assert settings.nllb_max_length == 128
    assert settings.nllb_num_beams == 4
    assert settings.llm_refinement_enabled is True
    assert settings.audio_sample_rate == 16_000
    assert settings.cors_allow_origins == ["http://localhost:5173"]
