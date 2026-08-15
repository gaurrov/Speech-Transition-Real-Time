"""
TranslationProvider: abstract interface for text translation.

The pipeline calls this per finalized (and optionally per partial)
transcript segment. Concrete providers implement low-latency cloud APIs
or the offline NLLB-200 fallback -- callers never branch on provider
type directly. The hybrid provider composes a cloud provider with the
NLLB fallback, so a transient cloud failure never fails the session.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.schemas import TranslationSegment


class TranslationError(Exception):
    """A translation attempt failed. ``code`` is a stable machine-readable key."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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

    async def close(self) -> None:
        """Release any held resources (HTTP clients, loaded models)."""
        return
