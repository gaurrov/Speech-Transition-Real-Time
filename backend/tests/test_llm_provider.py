"""Tests for the async LLM refinement provider and the factory."""
import httpx
import pytest

from app.config import Settings
from app.services.llm import create_llm_provider
from app.services.llm.base import LLMProvider, RefinementError
from app.services.llm.refinement_provider import LLMRefinementProvider


class _Recorder(httpx.MockTransport):
    def __init__(self, handler):
        super().__init__(handler)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return await super().handle_async_request(request)


def _provider(recorder: _Recorder, **settings_kwargs) -> LLMRefinementProvider:
    kwargs = {"llm_api_key": "test-key", **settings_kwargs}
    settings = Settings(**kwargs)
    client = httpx.AsyncClient(transport=recorder)
    return LLMRefinementProvider(settings=settings, client=client)


def _anthropic_handler(text: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"content": [{"type": "text", "text": text}]}
        )

    return handler


# --- Anthropic (default) ----------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_refine_changes_text() -> None:
    recorder = _Recorder(
        _anthropic_handler("We need to deploy the FastAPI service by Friday.")
    )
    provider = _provider(recorder)

    result = await provider.refine(
        segment_id="seg-1",
        text="we need to deploy the fast api service by friday",
        language="en",
    )
    assert result.segment_id == "seg-1"
    assert result.refined_text == "We need to deploy the FastAPI service by Friday."
    assert result.changed is True

    request = recorder.requests[0]
    assert request.method == "POST"
    assert request.url.host == "api.anthropic.com"
    assert request.headers["x-api-key"] == "test-key"
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = request.read().decode()
    assert '"system"' in body
    assert '"messages"' in body
    assert "we need to deploy the fast api service" in body
    await provider.close()


@pytest.mark.asyncio
async def test_anthropic_refine_unchanged_reports_changed_false() -> None:
    recorder = _Recorder(_anthropic_handler("Already clean."))
    provider = _provider(recorder)
    result = await provider.refine(
        segment_id="seg-1", text="Already clean.", language="en"
    )
    assert result.refined_text == "Already clean."
    assert result.changed is False
    await provider.close()


@pytest.mark.asyncio
async def test_anthropic_refine_passes_context() -> None:
    recorder = _Recorder(_anthropic_handler("Refined."))
    provider = _provider(recorder)
    await provider.refine(
        segment_id="seg-2",
        text="Refined.",
        language="en",
        context=["We use FastAPI.", "Deploy on Friday."],
    )
    body = recorder.requests[0].read().decode()
    assert "We use FastAPI." in body
    assert "Deploy on Friday." in body
    await provider.close()


@pytest.mark.asyncio
async def test_anthropic_refine_strips_wrapping_quotes() -> None:
    recorder = _Recorder(_anthropic_handler('"He said to deploy it."'))
    provider = _provider(recorder)
    result = await provider.refine(
        segment_id="seg-1", text="he said to deploy it", language="en"
    )
    assert result.refined_text == "He said to deploy it."
    assert result.changed is True
    await provider.close()


# --- OpenAI ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_refine_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Deploy by Friday."}}]},
        )

    recorder = _Recorder(handler)
    provider = _provider(recorder, llm_provider="openai")
    result = await provider.refine(
        segment_id="seg-1", text="deploy by friday", language="en"
    )
    assert result.refined_text == "Deploy by Friday."
    assert result.changed is True

    request = recorder.requests[0]
    assert request.headers["authorization"] == "Bearer test-key"
    body = request.read().decode()
    assert '"system"' in body
    assert '"user"' in body
    await provider.close()


# --- Errors and guards -------------------------------------------------------


@pytest.mark.asyncio
async def test_no_api_key_raises_config() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not send a request without a key")

    recorder = _Recorder(handler)
    provider = _provider(recorder, llm_api_key=None)
    with pytest.raises(RefinementError) as exc:
        await provider.refine(segment_id="seg-1", text="hello", language="en")
    assert exc.value.code == "llm_config"
    assert recorder.requests == []
    await provider.close()


@pytest.mark.asyncio
async def test_blank_text_skips_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("blank text must not call the API")

    recorder = _Recorder(handler)
    provider = _provider(recorder)
    result = await provider.refine(segment_id="seg-1", text="   ", language="en")
    assert result.refined_text == "   "
    assert result.changed is False
    assert recorder.requests == []
    await provider.close()


@pytest.mark.asyncio
async def test_connection_error_raises_llm_connection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    recorder = _Recorder(handler)
    provider = _provider(recorder)
    with pytest.raises(RefinementError) as exc:
        await provider.refine(segment_id="seg-1", text="hello", language="en")
    assert exc.value.code == "llm_connection"
    await provider.close()


@pytest.mark.asyncio
async def test_http_error_raises_llm_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    recorder = _Recorder(handler)
    provider = _provider(recorder)
    with pytest.raises(RefinementError) as exc:
        await provider.refine(segment_id="seg-1", text="hello", language="en")
    assert exc.value.code == "llm_api_error"
    await provider.close()


@pytest.mark.asyncio
async def test_malformed_body_raises_invalid_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": []})

    recorder = _Recorder(handler)
    provider = _provider(recorder)
    with pytest.raises(RefinementError) as exc:
        await provider.refine(segment_id="seg-1", text="hello", language="en")
    assert exc.value.code == "llm_invalid_output"
    await provider.close()


@pytest.mark.asyncio
async def test_empty_output_raises_invalid_output() -> None:
    recorder = _Recorder(_anthropic_handler("   "))
    provider = _provider(recorder)
    with pytest.raises(RefinementError) as exc:
        await provider.refine(segment_id="seg-1", text="hello", language="en")
    assert exc.value.code == "llm_invalid_output"
    await provider.close()


@pytest.mark.asyncio
async def test_paraphrase_guard_rejects_deviation() -> None:
    # A result that would summarize/rephrase the source is rejected.
    recorder = _Recorder(_anthropic_handler("Deploy."))
    provider = _provider(recorder)
    with pytest.raises(RefinementError) as exc:
        await provider.refine(
            segment_id="seg-1",
            text="We need to deploy the service to production on Friday morning",
            language="en",
        )
    assert exc.value.code == "llm_invalid_output"
    await provider.close()


@pytest.mark.asyncio
async def test_endpoint_override_is_used() -> None:
    recorder = _Recorder(_anthropic_handler("Refined."))
    provider = _provider(recorder, llm_endpoint="http://localhost:9999/v1/messages")
    await provider.refine(segment_id="seg-1", text="hello", language="en")
    assert recorder.requests[0].url.host == "localhost"
    assert recorder.requests[0].url.port == 9999
    await provider.close()


# --- Factory -----------------------------------------------------------------


def test_factory_returns_none_when_disabled(monkeypatch) -> None:
    settings = Settings(llm_refinement_enabled=False, llm_api_key="k")
    monkeypatch.setattr("app.services.llm.get_settings", lambda: settings)
    assert create_llm_provider() is None


def test_factory_returns_none_without_api_key(monkeypatch) -> None:
    settings = Settings(llm_refinement_enabled=True, llm_api_key=None)
    monkeypatch.setattr("app.services.llm.get_settings", lambda: settings)
    assert create_llm_provider() is None


def test_factory_returns_provider_when_enabled(monkeypatch) -> None:
    settings = Settings(llm_refinement_enabled=True, llm_api_key="k")
    monkeypatch.setattr("app.services.llm.get_settings", lambda: settings)
    provider = create_llm_provider()
    assert isinstance(provider, LLMProvider)


def test_enable_alias_parses_both_spellings(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_REFINEMENT", "false")
    assert Settings().llm_refinement_enabled is False
    monkeypatch.delenv("ENABLE_LLM_REFINEMENT")
    monkeypatch.setenv("LLM_REFINEMENT_ENABLED", "false")
    assert Settings().llm_refinement_enabled is False
