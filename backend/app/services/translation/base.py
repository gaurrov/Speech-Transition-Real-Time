"""
TranslationProvider: abstract interface for text translation.

The pipeline calls this per finalized (and optionally per partial)
transcript segment. Concrete providers implement low-latency cloud APIs
or the offline NLLB-200 fallback -- callers never branch on provider
type directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.schemas import TranslationSegment


class TranslationProvider(ABC):
    name: str

    @abstractmethod
    async def translate(
        self,
        *,
        segment_id: str,
        text: str,
        source_language: str,
        target_language: str,
        is_final: bool,
    ) -> TranslationSegment:
        """Translate a single transcript segment."""

    async def warm_up(self) -> None:
        """Optional hook for providers that need to load models/establish connections."""
        return

    async def health_check(self) -> bool:
        """Optional hook used by the hybrid router to decide cloud vs. fallback."""
        return True
