"""Configuration defaults tests."""
from app.config import Settings


def test_defaults_are_sane() -> None:
    settings = Settings()
    assert settings.asr_provider == "deepgram"
    assert settings.translation_provider == "cloud"
    assert settings.llm_refinement_enabled is True
    assert settings.audio_sample_rate == 16_000
    assert settings.cors_allow_origins == ["http://localhost:5173"]
