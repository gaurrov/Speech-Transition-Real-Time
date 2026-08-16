"""Tests for the NLLB service HTTP provider and factory wiring."""
import httpx
import pytest

from app.config import Settings
from app.services.translation import create_translation_provider
from app.services.translation.base import TranslationError
from app.services.translation.hybrid_provider import HybridTranslationProvider
from app.services.translation.nllb_service_provider import NLLBServiceProvider


def _provider(recorder: httpx.MockTransport, **settings_kwargs) -> NLLBServiceProvider:
    kwargs = {"nllb_service_url": "http://nllb:8000", **settings_kwargs}
    settings = Settings(**kwargs)
    client = httpx.AsyncClient(transport=recorder)
    return NLLBServiceProvider(settings=settings, client=client)


@pytest.mark.asyncio
async def test_service_translate_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"translated_text": "¡Hola!"})

    provider = _provider(httpx.MockTransport(handler))
    result = await provider.translate(
        segment_id="seg-1",
        text="Hello",
        source_language="en",
        target_language="es",
        is_final=True,
    )
    assert result.translated_text == "¡Hola!"
    assert result.source_language == "en"
    assert result.target_language == "es"
    assert result.provider == "nllb"
    assert result.is_final is True
    await provider.close()


@pytest.mark.asyncio
async def test_service_translate_sends_flores_codes() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"translated_text": "Namaste"})

    provider = _provider(httpx.MockTransport(handler))
    await provider.translate(
        segment_id="seg-1",
        text="Hello",
        source_language="en",
        target_language="hi",
        is_final=True,
    )
    assert captured["url"] == "http://nllb:8000/translate"
    assert '"source_lang":"eng_Latn"' in captured["body"]
    assert '"target_lang":"hin_Deva"' in captured["body"]
    await provider.close()


@pytest.mark.asyncio
async def test_service_translate_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(TranslationError) as exc:
        await provider.translate(
            segment_id="seg-1",
            text="Hello",
            source_language="en",
            target_language="es",
            is_final=True,
        )
    assert exc.value.code == "nllb_service_connection"
    await provider.close()


@pytest.mark.asyncio
async def test_service_translate_bad_status() -> None:
    provider = _provider(httpx.MockTransport(lambda request: httpx.Response(500, text="oops")))
    with pytest.raises(TranslationError) as exc:
        await provider.translate(
            segment_id="seg-1",
            text="Hello",
            source_language="en",
            target_language="es",
            is_final=True,
        )
    assert exc.value.code == "nllb_service_error"
    await provider.close()


@pytest.mark.asyncio
async def test_service_translate_malformed_body() -> None:
    provider = _provider(httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    with pytest.raises(TranslationError) as exc:
        await provider.translate(
            segment_id="seg-1",
            text="Hello",
            source_language="en",
            target_language="es",
            is_final=True,
        )
    assert exc.value.code == "nllb_service_error"
    await provider.close()


@pytest.mark.asyncio
async def test_service_translate_unsupported_language_fails_fast() -> None:
    sent = {"called": False}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["called"] = True
        return httpx.Response(200, json={"translated_text": "x"})

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(TranslationError) as exc:
        await provider.translate(
            segment_id="seg-1",
            text="Hello",
            source_language="xx",
            target_language="es",
            is_final=True,
        )
    assert exc.value.code == "unsupported_language"
    assert sent["called"] is False
    await provider.close()


@pytest.mark.asyncio
async def test_service_translate_blank_text_skips_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("blank text must not call the service")

    provider = _provider(httpx.MockTransport(handler))
    result = await provider.translate(
        segment_id="seg-1",
        text="   ",
        source_language="en",
        target_language="es",
        is_final=True,
    )
    assert result.translated_text == ""
    await provider.close()


@pytest.mark.asyncio
async def test_service_no_url_raises_config() -> None:
    provider = NLLBServiceProvider(settings=Settings(nllb_service_url=None))
    assert await provider.health_check() is False
    assert provider._base_url == ""


def test_factory_hybrid_uses_service_when_configured(monkeypatch) -> None:
    settings = Settings(translation_provider="hybrid", nllb_service_url="http://nllb:8000")
    monkeypatch.setattr("app.services.translation.get_settings", lambda: settings)
    provider = create_translation_provider()
    assert isinstance(provider, HybridTranslationProvider)
    assert isinstance(provider._nllb, NLLBServiceProvider)


def test_factory_nllb_uses_service_when_configured(monkeypatch) -> None:
    settings = Settings(translation_provider="nllb", nllb_service_url="http://nllb:8000")
    monkeypatch.setattr("app.services.translation.get_settings", lambda: settings)
    provider = create_translation_provider()
    assert isinstance(provider, NLLBServiceProvider)
