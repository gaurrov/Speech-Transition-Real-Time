"""
LLMProvider: abstract interface for asynchronous transcript refinement.

Critical constraint: implementations of this interface must NEVER be
awaited on the live captioning path. The websocket layer emits a final
transcript/translation to the client immediately, then fires refinement
as a background task; `REFINEMENT` events are pushed to the client
later, as a non-blocking correction to text already on screen.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.schemas import RefinementResult


class LLMProvider(ABC):
    @abstractmethod
    async def refine(
        self,
        *,
        segment_id: str,
        text: str,
        language: str,
        context: list[str] | None = None,
    ) -> RefinementResult:
        """
        Improve punctuation, capitalization, obvious ASR errors, and
        contextual terminology for a finalized segment. `context` is a
        short window of preceding finalized segments, used to keep
        terminology consistent across an utterance/meeting.
        """
