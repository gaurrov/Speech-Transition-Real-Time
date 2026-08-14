"""SilenceDetector unit tests."""
from app.services.vad.base import SilenceDetector


def test_short_silence_does_not_finalize() -> None:
    detector = SilenceDetector(finalize_ms=700, min_speech_ms=150)
    assert detector.should_finalize(silence_duration_ms=300, speech_duration_ms=2000) is False


def test_long_silence_finalizes() -> None:
    detector = SilenceDetector(finalize_ms=700, min_speech_ms=150)
    assert detector.should_finalize(silence_duration_ms=900, speech_duration_ms=2000) is True


def test_breath_noise_does_not_finalize() -> None:
    detector = SilenceDetector(finalize_ms=700, min_speech_ms=150)
    assert detector.should_finalize(silence_duration_ms=900, speech_duration_ms=50) is False
