# LLM transcript refinement (async, off the critical path)

Refinement is a **post-hoc** pass over already-finalized transcripts. It is
the only place an LLM is used; the models are never used for translation.

```
Transcript final
     │  (finalized utterances only)
     ▼
RefinementQueue (per-session, put_nowait — never awaited)
     │
     ▼
LLMProvider.refine(segment_id, text, language, context)
     │   Anthropic Messages or OpenAI-compatible endpoint (plain httpx)
     ▼
refined_transcript event  (only if changed)  +  latency event with refinement_ms
     │
     ▼
Frontend updates the on-screen segment in place (subtle "refined" highlight)
```

Rules that hold by design:

- **Never blocks the hot path.** A finalized segment is pushed onto an
  `asyncio.Queue` with `put_nowait`; the refinement worker runs independently,
  so translation and caption delivery are never delayed waiting on the LLM.
- **Strictly cosmetic + terminology.** The prompt may only fix
  punctuation/capitalization, sentence boundaries, and obvious ASR formatting
  of known technical terms. It must not add, summarize, rephrase, translate,
  or invent content. A length-ratio guard (0.4–1.6) rejects outputs that
  deviate too far from the source.
- **Never fail the meeting.** Any failure — missing config, connection error,
  HTTP 4xx/5xx, malformed/empty output — is logged and reported as a
  `RefinementError`; the original transcript stays on screen and all
  subsequent utterances keep running. A `latency` event with `refinement_ms`
  is sent after **every** attempt (success or failure) so refinement cost is
  measurable and the client is never left wondering.
- **Only when it helps.** If the refined output equals the source (normalized),
  the `refined_transcript` event is not sent at all (`changed: false`).
- **Rolling context window.** Up to `llm_context_segments` (default 4) recent
  finalized texts are passed alongside the segment being refined so
  terminology stays consistent across an utterance or meeting.

## Configuration

| Setting | Env | Default | Meaning |
|---|---|---|---|
| `llm_refinement_enabled` | `ENABLE_LLM_REFINEMENT` (alias `LLM_REFINEMENT_ENABLED`) | `true` | Master switch |
| `llm_provider` | `LLM_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `llm_api_key` | `LLM_API_KEY` | — | Provider API key |
| `llm_model` | `LLM_MODEL` | `claude-sonnet-4-6` | Model id |
| `llm_max_tokens` | `LLM_MAX_TOKENS` | `256` | Output cap |
| `llm_timeout_sec` | `LLM_TIMEOUT_SEC` | `20.0` | HTTP timeout |
| `llm_context_segments` | `LLM_CONTEXT_SEGMENTS` | `4` | Context window size |
| `llm_endpoint` | `LLM_ENDPOINT` | — | Override for local/mocked providers |

With no `LLM_API_KEY` (or `ENABLE_LLM_REFINEMENT=false`) the factory
`create_llm_provider()` returns `None` and refinement is skipped entirely —
the app behaves exactly as before, with no extra network calls.

## Protocol

Server → client events:

- `{"type": "refined_transcript", session_id, segment_id, refined_text, changed}` —
  sent only when the segment text actually improved.
- `{"type": "latency", session_id, segment_id, asr_ms, translation_ms, refinement_ms, end_to_end_ms}` —
  `refinement_ms` is set on the latency event emitted right after each
  refinement attempt (success or failure).

## Failure codes

`RefinementError.code` values surfaced in logs (non-fatal to the session):
`llm_config`, `llm_connection`, `llm_api_error`, `llm_invalid_output`.
