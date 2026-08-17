"""Tests for cloud / NLLB / hybrid translation providers and the factory."""
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from app.models.schemas import TranslationSegment
from app.services.translation import create_translation_provider
from app.services.translation.base import TranslationError, TranslationProvider
from app.services.translation.cloud_provider import CloudTranslationProvider
from app.services.translation.hybrid_provider import HybridTranslationProvider
from app.services.translation.nllb_provider import NLLBTranslationProvider

# --- Cloud provider (via httpx.MockTransport, no network) -------------------


class _Recorder(httpx.MockTransport):
    def __init__(self, handler):
        super().__init__(handler)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return await super().handle_async_request(request)


def _cloud_provider(recorder: _Recorder, **settings_kwargs) -> CloudTranslationProvider:
    kwargs = {"cloud_translation_api_key": "test-key", **settings_kwargs}
    settings = Settings(**kwargs)
    client = httpx.AsyncClient(transport=recorder)
    return CloudTranslationProvider(settings=settings, client=client)


@pytest.mark.asyncio
async def test_cloud_translate_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {"translations": [{"translatedText": "Hola"}]}}
        )

    recorder = _Recorder(handler)
    provider = _cloud_provider(recorder)
    result = await provider.translate(
        segment_id="seg-1",
        text="Hello",
        source_language="en",
        target_language="es",
        is_final=True,
    )

    assert result.translated_text == "Hola"
    assert result.source_text == "Hello"
    assert result.source_language == "en"
    assert result.target_language == "es"
    assert result.is_final is True
    assert result.provider == "cloud"

    request = recorder.requests[0]
    assert request.method == "POST"
    assert request.url.params["key"] == "test-key"
    body = request.read().decode()
    assert '"source":"en"' in body
    assert '"target":"es"' in body
    await provider.close()


@pytest.mark.asyncio
async def test_cloud_translate_auto_source_omits_source() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {"translations": [{"translatedText": "Hola"}]}}
        )

    recorder = _Recorder(handler)
    provider = _cloud_provider(recorder)
    result = await provider.translate(
        segment_id="seg-1",
        text="Hello",
        source_language="auto",
        target_language="es",
        is_final=False,
    )
    assert result.is_final is False
    body = recorder.requests[0].read().decode()
    assert "source" not in body
    await provider.close()


@pytest.mark.asyncio
async def test_cloud_translate_no_api_key_raises_config() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not send a request without a key")

    recorder = _Recorder(handler)
    provider = _cloud_provider(recorder, cloud_translation_api_key=None)
    with pytest.raises(TranslationError) as exc:
        await provider.translate(
            segment_id="seg-1",
            text="Hello",
            source_language="en",
            target_language="es",
            is_final=True,
        )
    assert exc.value.code == "cloud_config"
    assert recorder.requests == []
    await provider.close()


@pytest.mark.asyncio
async def test_cloud_translate_blank_text_skips_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("blank text must not call the API")

    recorder = _Recorder(handler)
    provider = _cloud_provider(recorder)
    result = await provider.translate(
        segment_id="seg-1",
        text="   ",
        source_language="en",
        target_language="es",
        is_final=True,
    )
    assert result.translated_text == ""
    assert recorder.requests == []
    await provider.close()


@pytest.mark.asyncio
async def test_cloud_translate_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    recorder = _Recorder(handler)
    provider = _cloud_provider(recorder)
    with pytest.raises(TranslationError) as exc:
        await provider.translate(
            segment_id="seg-1",
            text="Hello",
            source_language="en",
            target_language="es",
            is_final=True,
        )
    assert exc.value.code == "cloud_connection"
    await provider.close()


@pytest.mark.asyncio
async def test_cloud_translate_bad_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="invalid request")

    recorder = _Recorder(handler)
    provider = _cloud_provider(recorder)
    with pytest.raises(TranslationError) as exc:
        await provider.translate(
            segment_id="seg-1",
            text="Hello",
            source_language="en",
            target_language="es",
            is_final=True,
        )
    assert exc.value.code == "cloud_translation_error"
    await provider.close()


@pytest.mark.asyncio
async def test_cloud_translate_malformed_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {}})

    recorder = _Recorder(handler)
    provider = _cloud_provider(recorder)
    with pytest.raises(TranslationError) as exc:
        await provider.translate(
            segment_id="seg-1",
            text="Hello",
            source_language="en",
            target_language="es",
            is_final=True,
        )
    assert exc.value.code == "cloud_translation_error"
    await provider.close()


def test_cloud_provider_rejects_non_google() -> None:
    with pytest.raises(TranslationError) as exc:
        CloudTranslationProvider(
            settings=Settings(cloud_translation_provider_name="deepl")
        )
    assert exc.value.code == "cloud_config"


@pytest.mark.asyncio
async def test_cloud_health_check_and_close() -> None:
    provider = CloudTranslationProvider(
        settings=Settings(cloud_translation_api_key=None)
    )
    assert await provider.health_check() is False
    await provider.close()

    provider = CloudTranslationProvider(settings=Settings(cloud_translation_api_key="k"))
    assert await provider.health_check() is True
    await provider.close()


# --- NLLB provider (engine is monkeypatched; torch is not installed) ---------


@pytest.fixture
def clear_nllb_cache():
    """Reset the process-wide NLLB model cache so monkeypatched loads re-run."""
    from app.services.translation.nllb_provider import _reset_model_cache

    _reset_model_cache()
    yield
    _reset_model_cache()


@pytest.mark.asyncio
async def test_nllb_warm_up_missing_deps_raises_unavailable(clear_nllb_cache, monkeypatch) -> None:
    provider = NLLBTranslationProvider(settings=Settings())

    def _load():
        raise ImportError("no torch")

    monkeypatch.setattr(provider, "_load_model", _load)
    with pytest.raises(TranslationError) as exc:
        await provider.warm_up()
    assert exc.value.code == "nllb_model_unavailable"


@pytest.mark.asyncio
async def test_nllb_warm_up_load_error_raises_unavailable(clear_nllb_cache, monkeypatch) -> None:
    provider = NLLBTranslationProvider(settings=Settings())

    def _load():
        raise RuntimeError("corrupt weights")

    monkeypatch.setattr(provider, "_load_model", _load)
    with pytest.raises(TranslationError) as exc:
        await provider.warm_up()
    assert exc.value.code == "nllb_model_unavailable"


@pytest.mark.asyncio
async def test_nllb_translate_calls_engine_with_language_codes(clear_nllb_cache, monkeypatch) -> None:
    provider = NLLBTranslationProvider(settings=Settings())
    calls = []

    def _load():
        return object(), object()

    def _translate_engine(text, source_language, target_language):
        calls.append((text, source_language, target_language))
        return "¡Hola!"

    monkeypatch.setattr(provider, "_load_model", _load)
    monkeypatch.setattr(provider, "_translate_engine", _translate_engine)

    result = await provider.translate(
        segment_id="seg-1",
        text="Hello",
        source_language="en",
        target_language="es",
        is_final=True,
    )
    assert result.translated_text == "¡Hola!"
    assert result.provider == "nllb"
    assert result.is_final is True
    assert calls == [("Hello", "en", "es")]


@pytest.mark.asyncio
async def test_nllb_translate_unsupported_language_fails_fast(clear_nllb_cache, monkeypatch) -> None:
    provider = NLLBTranslationProvider(settings=Settings())
    called = {"engine": False}

    def _load():
        return object(), object()

    def _translate_engine(text, source_language, target_language):
        called["engine"] = True
        return text

    monkeypatch.setattr(provider, "_load_model", _load)
    monkeypatch.setattr(provider, "_translate_engine", _translate_engine)

    with pytest.raises(TranslationError) as exc:
        await provider.translate(
            segment_id="seg-1",
            text="Hello",
            source_language="xx",
            target_language="es",
            is_final=True,
        )
    assert exc.value.code == "unsupported_language"
    assert called["engine"] is False


# --- Hybrid provider ---------------------------------------------------------


class _FakeProvider(TranslationProvider):
    def __init__(
        self,
        name: str,
        result: TranslationSegment,
        error: TranslationError | None = None,
    ):
        self.name = name
        self._result = result
        self.error = error
        self.calls = 0
        self.closed = False

    async def translate(self, **kwargs) -> TranslationSegment:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self._result

    async def close(self) -> None:
        self.closed = True


def _segment(**overrides) -> TranslationSegment:
    defaults = {
        "segment_id": "seg-1",
        "source_text": "Hello",
        "translated_text": "translated",
        "source_language": "en",
        "target_language": "es",
        "is_final": True,
        "provider": "x",
    }
    defaults.update(overrides)
    return TranslationSegment(**defaults)


def _hybrid_settings(**overrides) -> Settings:
    """Settings with a cloud API key so the hybrid provider doesn't short-circuit."""
    kwargs = {"cloud_translation_api_key": "test-key", **overrides}
    return Settings(**kwargs)


@pytest.mark.asyncio
async def test_hybrid_cloud_success_skips_fallback() -> None:
    cloud = _FakeProvider("cloud", _segment(provider="cloud"))
    nllb = _FakeProvider("nllb", _segment(provider="nllb"))
    hybrid = HybridTranslationProvider(settings=_hybrid_settings(), cloud=cloud, nllb=nllb)

    result = await hybrid.translate(
        segment_id="seg-1",
        text="Hello",
        source_language="en",
        target_language="es",
        is_final=True,
    )
    assert result.provider == "cloud"
    assert cloud.calls == 1
    assert nllb.calls == 0


@pytest.mark.asyncio
async def test_hybrid_cloud_failure_falls_back_to_nllb() -> None:
    cloud = _FakeProvider(
        "cloud",
        _segment(provider="cloud"),
        error=TranslationError("cloud_connection", "boom"),
    )
    nllb = _FakeProvider("nllb", _segment(provider="nllb"))
    hybrid = HybridTranslationProvider(settings=_hybrid_settings(), cloud=cloud, nllb=nllb)

    result = await hybrid.translate(
        segment_id="seg-1",
        text="Hello",
        source_language="en",
        target_language="es",
        is_final=True,
    )
    assert result.provider == "nllb"
    assert cloud.calls == 1
    assert nllb.calls == 1


@pytest.mark.asyncio
async def test_hybrid_both_fail_raises_translation_failed() -> None:
    cloud = _FakeProvider(
        "cloud",
        _segment(provider="cloud"),
        error=TranslationError("cloud_connection", "boom"),
    )
    nllb = _FakeProvider(
        "nllb",
        _segment(provider="nllb"),
        error=TranslationError("nllb_model_unavailable", "no torch"),
    )
    hybrid = HybridTranslationProvider(settings=_hybrid_settings(), cloud=cloud, nllb=nllb)

    with pytest.raises(TranslationError) as exc:
        await hybrid.translate(
            segment_id="seg-1",
            text="Hello",
            source_language="en",
            target_language="es",
            is_final=True,
        )
    assert exc.value.code == "translation_failed"


@pytest.mark.asyncio
async def test_hybrid_warm_up_noop_and_close() -> None:
    cloud = _FakeProvider("cloud", _segment(provider="cloud"))
    nllb = _FakeProvider("nllb", _segment(provider="nllb"))
    hybrid = HybridTranslationProvider(settings=_hybrid_settings(), cloud=cloud, nllb=nllb)

    await hybrid.warm_up()
    await hybrid.close()
    assert cloud.closed is True
    assert nllb.closed is True


# --- Factory -----------------------------------------------------------------


def test_factory_hybrid_mode(monkeypatch) -> None:
    settings = Settings(translation_provider="hybrid")
    monkeypatch.setattr("app.services.translation.get_settings", lambda: settings)
    provider = create_translation_provider()
    assert isinstance(provider, HybridTranslationProvider)


def test_factory_cloud_mode(monkeypatch) -> None:
    settings = Settings(translation_provider="cloud")
    monkeypatch.setattr("app.services.translation.get_settings", lambda: settings)
    provider = create_translation_provider()
    assert isinstance(provider, CloudTranslationProvider)


def test_factory_nllb_mode(monkeypatch) -> None:
    settings = Settings(
        translation_provider="nllb",
        nllb_service_url="http://nllb:8001",
    )
    monkeypatch.setattr("app.services.translation.get_settings", lambda: settings)
    provider = create_translation_provider()
    # With nllb_service_url set, the factory picks the service provider.
    from app.services.translation.nllb_service_provider import NLLBServiceProvider

    assert isinstance(provider, NLLBServiceProvider)


def test_factory_unknown_mode_raises_config(monkeypatch) -> None:
    settings = Settings(translation_provider="hybrid")
    settings.translation_provider = "bogus"
    monkeypatch.setattr("app.services.translation.get_settings", lambda: settings)
    with pytest.raises(TranslationError) as exc:
        create_translation_provider()
    assert exc.value.code == "translation_config"


# --- Google Cloud is optional: NLLB works without Google credentials ---------


def test_nllb_starts_without_google_key(monkeypatch) -> None:
    """Application starts with NLLB and no Google key."""
    settings = Settings(
        translation_provider="nllb",
        cloud_translation_api_key=None,
        nllb_service_url="http://nllb:8001",
    )
    monkeypatch.setattr("app.services.translation.get_settings", lambda: settings)
    provider = create_translation_provider()
    from app.services.translation.nllb_service_provider import NLLBServiceProvider

    assert isinstance(provider, NLLBServiceProvider)


@pytest.mark.asyncio
async def test_nllb_translates_without_google_key() -> None:
    """NLLB translation works without Google key."""
    from app.services.translation.nllb_service_provider import NLLBServiceProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"translated_text": "Hola mundo"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = NLLBServiceProvider(
        settings=Settings(
            nllb_service_url="http://nllb:8001",
            cloud_translation_api_key=None,
        ),
        client=client,
    )
    result = await provider.translate(
        segment_id="seg-1",
        text="Hello world",
        source_language="en",
        target_language="es",
        is_final=True,
    )
    assert result.translated_text == "Hola mundo"
    assert result.provider == "nllb"
    await provider.close()


def test_cloud_provider_not_imported_when_nllb(monkeypatch) -> None:
    """Cloud translation code should not be imported when NLLB is selected."""
    import sys

    settings = Settings(
        translation_provider="nllb",
        cloud_translation_api_key=None,
        nllb_service_url="http://nllb:8001",
    )
    monkeypatch.setattr("app.services.translation.get_settings", lambda: settings)
    # Ensure cloud_provider module is not already loaded from a prior test
    sys.modules.pop("app.services.translation.cloud_provider", None)
    sys.modules.pop("app.services.translation.hybrid_provider", None)

    provider = create_translation_provider()
    from app.services.translation.nllb_service_provider import NLLBServiceProvider

    assert isinstance(provider, NLLBServiceProvider)
    assert "app.services.translation.cloud_provider" not in sys.modules
    assert "app.services.translation.hybrid_provider" not in sys.modules


def test_missing_google_key_does_not_fail_startup_with_nllb() -> None:
    """Startup should not fail or warn when Google key is missing but NLLB is configured."""
    from app.services.translation import warn_on_translation_misconfiguration

    settings = Settings(
        translation_provider="nllb",
        cloud_translation_api_key=None,
        nllb_service_url="http://nllb:8001",
    )
    # Should not raise -- no warning for NLLB mode when NLLB is available.
    warn_on_translation_misconfiguration(settings)


# --- probe_nllb_service (async probe) --------------------------------------


@pytest.mark.asyncio
async def test_probe_nllb_service_returns_true_when_reachable(monkeypatch) -> None:
    """probe_nllb_service returns True when the NLLB service responds 200."""
    import app.services.translation as trans_mod

    monkeypatch.setattr(
        "app.services.translation.get_settings",
        lambda: Settings(nllb_service_url="http://nllb:8001"),
    )
    monkeypatch.setattr(trans_mod, "_nllb_service_reachable", None)
    monkeypatch.setattr(trans_mod, "_nllb_probe_ts", 0.0)

    async def _mock_health(self) -> bool:
        return True

    monkeypatch.setattr(
        "app.services.translation.nllb_service_provider.NLLBServiceProvider.health_check",
        _mock_health,
    )
    monkeypatch.setattr(
        "app.services.translation.nllb_service_provider.NLLBServiceProvider.close",
        AsyncMock(),
    )
    from app.services.translation import probe_nllb_service

    result = await probe_nllb_service()
    assert result is True


@pytest.mark.asyncio
async def test_probe_nllb_service_returns_false_when_unreachable(monkeypatch) -> None:
    """probe_nllb_service returns False when the NLLB service is down."""
    import app.services.translation as trans_mod

    monkeypatch.setattr(
        "app.services.translation.get_settings",
        lambda: Settings(nllb_service_url="http://nllb:8001"),
    )
    monkeypatch.setattr(trans_mod, "_nllb_service_reachable", None)
    monkeypatch.setattr(trans_mod, "_nllb_probe_ts", 0.0)

    async def _mock_health(self) -> bool:
        return False

    monkeypatch.setattr(
        "app.services.translation.nllb_service_provider.NLLBServiceProvider.health_check",
        _mock_health,
    )
    monkeypatch.setattr(
        "app.services.translation.nllb_service_provider.NLLBServiceProvider.close",
        AsyncMock(),
    )
    from app.services.translation import probe_nllb_service

    result = await probe_nllb_service()
    assert result is False


@pytest.mark.asyncio
async def test_probe_nllb_service_uses_cache(monkeypatch) -> None:
    """Second call within TTL returns cached result without probing again."""
    import app.services.translation as trans_mod

    monkeypatch.setattr(
        "app.services.translation.get_settings",
        lambda: Settings(nllb_service_url="http://nllb:8001"),
    )
    # Set cache to a known value within TTL
    import time

    monkeypatch.setattr(trans_mod, "_nllb_service_reachable", True)
    monkeypatch.setattr(trans_mod, "_nllb_probe_ts", time.monotonic())
    monkeypatch.setattr(trans_mod, "_NLLB_PROBE_TTL_SECONDS", 999.0)

    call_count = {"n": 0}

    async def _mock_health(self) -> bool:
        call_count["n"] += 1
        return False  # would return False if probed, but cache says True

    monkeypatch.setattr(
        "app.services.translation.nllb_service_provider.NLLBServiceProvider.health_check",
        _mock_health,
    )
    monkeypatch.setattr(
        "app.services.translation.nllb_service_provider.NLLBServiceProvider.close",
        AsyncMock(),
    )
    from app.services.translation import probe_nllb_service

    result = await probe_nllb_service()
    assert result is True  # from cache, not from probe
    assert call_count["n"] == 0  # health_check was never called


@pytest.mark.asyncio
async def test_probe_nllb_service_no_url_falls_to_offline(monkeypatch) -> None:
    """When nllb_service_url is unset, probe falls back to offline runtime check."""
    import app.services.translation as trans_mod

    monkeypatch.setattr(
        "app.services.translation.get_settings",
        lambda: Settings(nllb_service_url=None),
    )
    monkeypatch.setattr(trans_mod, "_nllb_service_reachable", None)
    monkeypatch.setattr(trans_mod, "_nllb_probe_ts", 0.0)
    monkeypatch.setattr(trans_mod, "_offline_runtime_available", lambda: True)

    from app.services.translation import probe_nllb_service

    result = await probe_nllb_service()
    assert result is True
