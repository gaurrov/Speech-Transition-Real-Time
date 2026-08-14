"""
LLMRefinementProvider: default async post-processing implementation.

Runs strictly after an utterance is finalized and off the latency-
critical path (see base.py). Scaffold only.
"""
from __future__ import annotations

from app.config import get_settings
from app.models.schemas import RefinementResult
from app.services.llm.base import LLMProvider


class LLMRefinementProvider(LLMProvider):
    def __init__(self) -> None:
        self._settings = get_settings()

    async def refine(
        self,
        *,
        segment_id: str,
        text: str,
        language: str,
        context: list[str] | None = None,
    ) -> RefinementResult:
        # TODO: call self._settings.llm_provider's API with a tightly
        # scoped prompt: fix punctuation/casing/obvious ASR errors only,
        # preserve meaning, return refined text + whether it changed.
        raise NotImplementedError("LLMRefinementProvider.refine is not yet implemented")
