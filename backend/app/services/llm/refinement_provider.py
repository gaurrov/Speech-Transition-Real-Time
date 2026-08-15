"""
LLMRefinementProvider: async, non-blocking transcript proofreader.

Talks to a chat-completions-style LLM API (Anthropic Messages or OpenAI
Chat Completions) directly with httpx -- no SDK, minimal footprint. The
endpoint is configurable (``llm_endpoint``) so proxies and tests can point
it elsewhere.

Runs strictly off the latency-critical captioning path (see base.py): the
transport never awaits ``refine`` before emitting a final transcript or
translation. On any failure it raises ``RefinementError`` and the caller
keeps the original transcript -- refinement is best-effort by design.
"""
from __future__ import annotations

import httpx
import structlog

from app.config import Settings, get_settings
from app.models.schemas import RefinementResult
from app.services.llm.base import LLMProvider, RefinementError

logger = structlog.get_logger(__name__)

ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = """You are a transcription proofreader for a live meeting captioning system. \
Your only job is to fix unambiguous ASR (speech-recognition) formatting errors in the transcript.

Allowed changes:
- Add or fix punctuation.
- Fix capitalization (sentence starts, proper nouns, product/technical names).
- Fix obvious formatting of technical terms (e.g. "fast api" -> "FastAPI", \
"rest api" -> "REST API", "kubernetes" -> "Kubernetes").

Forbidden changes:
- Do NOT add information, words, or sentences.
- Do NOT summarize, truncate, or rephrase.
- Do NOT change meaning. Do NOT translate. Reply in the SAME language as the transcript.

If the transcript is already clean, return it verbatim.
Return ONLY the corrected transcript text: no explanation, no quotes, no preamble."""


class LLMRefinementProvider(LLMProvider):
    name = "llm"

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or httpx.AsyncClient(
            timeout=self._settings.llm_timeout_sec
        )

    @property
    def _endpoint(self) -> str:
        return self._settings.llm_endpoint or (
            ANTHROPIC_ENDPOINT
            if self._settings.llm_provider == "anthropic"
            else OPENAI_ENDPOINT
        )

    async def refine(
        self,
        *,
        segment_id: str,
        text: str,
        language: str,
        context: list[str] | None = None,
    ) -> RefinementResult:
        if not text.strip():
            return RefinementResult(segment_id=segment_id, refined_text=text, changed=False)

        api_key = self._settings.llm_api_key
        if not api_key:
            raise RefinementError("llm_config", "LLM API key is not configured")

        payload, headers = self._build_request(api_key, text, context)

        try:
            response = await self._client.post(self._endpoint, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise RefinementError("llm_connection", f"LLM request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:200]
            raise RefinementError(
                "llm_api_error",
                f"LLM API error (HTTP {response.status_code}): {detail}",
            )

        refined = self._extract_text(response)
        refined = self._clean_output(refined)
        if not refined:
            raise RefinementError("llm_invalid_output", "LLM returned empty output")
        if self._too_different(text, refined):
            raise RefinementError(
                "llm_invalid_output",
                "LLM output deviates too far from the source transcript",
            )

        return RefinementResult(
            segment_id=segment_id,
            refined_text=refined,
            changed=refined != text,
        )

    def _build_request(self, api_key: str, text: str, context: list[str] | None) -> tuple[dict, dict]:
        user_prompt = self._user_prompt(text, context)
        if self._settings.llm_provider == "anthropic":
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload: dict = {
                "model": self._settings.llm_model,
                "max_tokens": self._settings.llm_max_tokens,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            }
        else:
            headers = {
                "authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            }
            payload = {
                "model": self._settings.llm_model,
                "max_tokens": self._settings.llm_max_tokens,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            }
        return payload, headers

    @staticmethod
    def _user_prompt(text: str, context: list[str] | None) -> str:
        if context:
            lines = "\n".join(f"- {item}" for item in context)
            return f"Earlier context:\n{lines}\n\nTranscript:\n\n{text}"
        return f"Transcript:\n\n{text}"

    def _extract_text(self, response: httpx.Response) -> str:
        try:
            body = response.json()
            if self._settings.llm_provider == "anthropic":
                for block in body.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
                return ""
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RefinementError(
                "llm_invalid_output", "LLM returned an unexpected response"
            ) from exc
        return content if isinstance(content, str) else ""

    @staticmethod
    def _clean_output(raw: str) -> str:
        out = raw.strip()
        if len(out) >= 2 and out[0] == out[-1] and out[0] in ('"', "'", "`"):
            out = out[1:-1].strip()
        return out

    @staticmethod
    def _too_different(text: str, refined: str) -> bool:
        if not text.strip():
            return False
        ratio = len(refined) / len(text)
        return ratio > 1.6 or ratio < 0.4

    async def close(self) -> None:
        await self._client.aclose()
