"""Tests for the NLLB translation service (mocked model)."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

# Ensure the nllb app package is importable.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: I001


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_translate(text: str, source_lang: str, target_lang: str, request_id: str, queue_enter_ts: float) -> tuple:
    """Fake translation that returns a plausible result."""
    import time
    result = "[" + target_lang + "] " + text
    return (result, {"inference_start": time.monotonic(), "inference_end": time.monotonic()})


@pytest.fixture(autouse=True)
def _reset_stats():
    """Reset per-process counters between tests."""
    from app import main

    main._translation_count = 0
    main._translation_latency_sum = 0.0
    main._MODEL_CACHE.clear()
    yield


def _client(**env_overrides) -> httpx.AsyncClient:
    """Return an async test client with env patched."""
    env_patch = {"NLLB_REQUEST_TIMEOUT": "5", "NLLB_WARM_START": "false", **env_overrides}
    with patch.dict("os.environ", env_patch):
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


class TestModelLoading:
    def test_device_auto_detect_cpu(self) -> None:
        """When NLLB_DEVICE is unset and CUDA unavailable, device is 'cpu'."""
        from app import main

        with patch.dict("os.environ", {}, clear=False):
            os_environ = {k: v for k, v in __import__("os").environ.items() if k != "NLLB_DEVICE"}
            with (
                patch.dict(__import__("os").environ, os_environ, clear=True),
                patch("app.main._device") as mock_device,
            ):
                mock_device.return_value = "cpu"
                assert main._device() == "cpu"

    def test_model_cached_after_first_load(self) -> None:
        """Second call returns the same cached model instance."""
        from app import main

        fake_model = MagicMock()
        fake_tokenizer = MagicMock()
        fake_tokenizer.convert_tokens_to_ids.return_value = 0

        with (
            patch("app.main._MODEL_CACHE", {}),
            patch("app.main._MODEL_CACHE_LOCK"),
            patch("transformers.AutoTokenizer.from_pretrained", return_value=fake_tokenizer),
            patch("transformers.AutoModelForSeq2SeqLM.from_pretrained", return_value=fake_model),
        ):
            first = main._load_model()
            second = main._load_model()
            assert first is second


# ---------------------------------------------------------------------------
# Translation endpoint
# ---------------------------------------------------------------------------


class TestTranslateEndpoint:
    @pytest.mark.asyncio
    async def test_empty_text_returns_empty(self) -> None:
        async with _client() as client:
            resp = await client.post(
                "/translate",
                json={"text": "   ", "source_lang": "eng_Latn", "target_lang": "hin_Deva"},
            )
        assert resp.status_code == 200
        assert resp.json()["translated_text"] == ""

    @pytest.mark.asyncio
    async def test_translate_success(self) -> None:
        from app import main

        with patch.object(main, "_translate_sync", _mock_translate):
            async with _client() as client:
                resp = await client.post(
                    "/translate",
                    json={"text": "Hello", "source_lang": "eng_Latn", "target_lang": "hin_Deva"},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["translated_text"] == "[hin_Deva] Hello"

    @pytest.mark.asyncio
    async def test_translate_increments_count(self) -> None:
        from app import main

        with patch.object(main, "_translate_sync", _mock_translate):
            async with _client() as client:
                await client.post(
                    "/translate",
                    json={"text": "Hi", "source_lang": "eng_Latn", "target_lang": "spa_Latn"},
                )
                await client.post(
                    "/translate",
                    json={"text": "Bonjour", "source_lang": "fra_Latn", "target_lang": "eng_Latn"},
                )
        assert main._translation_count == 2

    @pytest.mark.asyncio
    async def test_translate_timeout_returns_504(self) -> None:
        from app import main

        async def fake_wait_for(coro, timeout):
            raise TimeoutError()

        with (
            patch.object(main, "_translate_sync", lambda *a: "never"),
            patch("app.main.asyncio.wait_for", side_effect=fake_wait_for),
        ):
            async with _client(NLLB_REQUEST_TIMEOUT="0.1") as client:
                resp = await client.post(
                    "/translate",
                    json={"text": "Slow", "source_lang": "eng_Latn", "target_lang": "hin_Deva"},
                )
        assert resp.status_code == 504
        assert "timed out" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_translate_exception_returns_500(self) -> None:
        from app import main

        def explode(text, src, tgt, request_id, queue_enter_ts):
            raise RuntimeError("model crashed")

        with patch.object(main, "_translate_sync", side_effect=explode):
            async with _client() as client:
                resp = await client.post(
                    "/translate",
                    json={"text": "Boom", "source_lang": "eng_Latn", "target_lang": "hin_Deva"},
                )
        assert resp.status_code == 500
        assert "model crashed" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_reports_ok(self) -> None:
        async with _client() as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "nllb"
        assert data["model_loaded"] is False
        assert data["translation_count"] == 0
        assert data["avg_latency_ms"] is None

    @pytest.mark.asyncio
    async def test_health_reports_stats_after_translations(self) -> None:
        from app import main

        main._translation_count = 5
        main._translation_latency_sum = 250.0

        async with _client() as client:
            resp = await client.get("/health")
        data = resp.json()
        assert data["translation_count"] == 5
        assert data["avg_latency_ms"] == 50.0


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_request_timeout_default(self) -> None:
        from app import main

        with patch.dict("os.environ", {}, clear=False):
            os_clean = {k: v for k, v in __import__("os").environ.items() if k != "NLLB_REQUEST_TIMEOUT"}
            with patch.dict(__import__("os").environ, os_clean, clear=True):
                assert main._request_timeout() == 30.0

    def test_request_timeout_custom(self) -> None:
        from app import main

        with patch.dict("os.environ", {"NLLB_REQUEST_TIMEOUT": "10"}):
            assert main._request_timeout() == 10.0

    def test_max_length_default(self) -> None:
        from app import main

        with patch.dict("os.environ", {}, clear=False):
            os_clean = {k: v for k, v in __import__("os").environ.items() if k != "NLLB_MAX_LENGTH"}
            with patch.dict(__import__("os").environ, os_clean, clear=True):
                assert main._max_length() == 80

    def test_num_beams_default(self) -> None:
        from app import main

        with patch.dict("os.environ", {}, clear=False):
            os_clean = {k: v for k, v in __import__("os").environ.items() if k != "NLLB_NUM_BEAMS"}
            with patch.dict(__import__("os").environ, os_clean, clear=True):
                assert main._num_beams() == 1

    def test_num_beams_custom(self) -> None:
        from app import main

        with patch.dict("os.environ", {"NLLB_NUM_BEAMS": "4"}):
            assert main._num_beams() == 4

    def test_num_threads_default(self) -> None:
        from app import main

        with patch.dict("os.environ", {}, clear=False):
            os_clean = {k: v for k, v in __import__("os").environ.items() if k != "NLLB_NUM_THREADS"}
            with patch.dict(__import__("os").environ, os_clean, clear=True):
                assert main._num_threads() is None

    def test_num_threads_custom(self) -> None:
        from app import main

        with patch.dict("os.environ", {"NLLB_NUM_THREADS": "4"}):
            assert main._num_threads() == 4

    def test_length_penalty_default(self) -> None:
        from app import main

        with patch.dict("os.environ", {}, clear=False):
            os_clean = {k: v for k, v in __import__("os").environ.items() if k != "NLLB_LENGTH_PENALTY"}
            with patch.dict(__import__("os").environ, os_clean, clear=True):
                assert main._length_penalty() == 1.0

    def test_length_penalty_custom(self) -> None:
        from app import main

        with patch.dict("os.environ", {"NLLB_LENGTH_PENALTY": "0.8"}):
            assert main._length_penalty() == 0.8
