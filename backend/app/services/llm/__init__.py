"""
LLM refinement provider factory.

Returns a provider only when refinement is enabled AND an API key is
configured; otherwise returns ``None`` so the transport simply skips the
refinement pass. The hot path (ASR -> translation -> client) never depends
on this module -- it is only ever consulted to spin up the background
refinement worker.
"""
from __future__ import annotations

from app.config import get_settings
from app.services.llm.base import LLMProvider
from app.services.llm.refinement_provider import LLMRefinementProvider

__all__ = ["LLMProvider", "LLMRefinementProvider", "create_llm_provider"]


def create_llm_provider() -> LLMProvider | None:
    settings = get_settings()
    if not settings.llm_refinement_enabled:
        return None
    if not settings.llm_api_key:
        return None
    return LLMRefinementProvider(settings=settings)
