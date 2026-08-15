# Translation: hybrid cloud → NLLB-200 fallback

Translation is handled by a small provider family behind the
`TranslationProvider` interface. The pipeline calls **one** abstraction; it
never branches on provider type or on language pairs.

```
Transcript final
     │  (finalized utterances only)
     ▼
TranslationQueue (per-session, ordered)
     │
     ▼
HybridTranslationProvider
     ├─ CloudTranslationProvider  ── succeeds ──► cloud text
     │     (Google Cloud Translation v2 REST, low latency)
     └─ on TranslationError ▼
        NLLBTranslationProvider ── succeeds ──► NLLB text (provider="nllb")
        (NLLB-200 distilled 600M, offline)
            └─ also fails ──► error event "translation_failed" (non-fatal)
```

Rules that hold by design:

- **Cloud first.** The cloud API is the primary, low-latency path.
- **NLLB fallback on failure.** Any `TranslationError` from the cloud provider
  (missing key, network error, HTTP 4xx/5xx, malformed body) triggers the
  offline provider for that utterance.
- **Never fail the meeting.** A transient translation failure is reported to
  the client as an `error` event with code `translation_failed`; the session
  and all subsequent utterances keep running. The frontend treats that code
  as non-fatal.
- **Finalized utterances only.** Partials stream straight to the client and
  are never queued for translation.
- **Provider-specific codes are resolved centrally** (see below); the
  pipeline contains zero hardcoded language-pair conditionals.
- **No LLM as translator.** The models are not used for translation; the LLM
  is reserved for transcript refinement (see `docs/refinement.md` if present).

## Provider modes

Selected by `TRANSLATION_PROVIDER` (`translation_provider` setting):

| Mode | Behavior |
|---|---|
| `hybrid` (default) | cloud first, NLLB-200 fallback |
| `cloud` | cloud only; failures surface as `translation_failed` |
| `nllb` | NLLB-200 only |

The factory `create_translation_provider()` in
`backend/app/services/translation/__init__.py` reads the setting and also
applies the `TRANSLATION_EXTRA_LANGUAGES` registry entries before returning.

## Central language registry

`backend/app/services/translation/languages.py` is the single source of truth.
Each `Language` entry carries:

- `iso_code` — canonical code used across the app (`en`, `hi`, `ta`, …);
- `display_name` — human-readable name;
- `cloud_code` — cloud API code (defaults to `iso_code`);
- `nllb_code` — NLLB-200 FLORES-200 token (`hin_Deva`, `tam_Taml`, …).

Resolution helpers:

- `cloud_code("auto")` → `"auto"` (cloud performs source detection when the
  `source` param is omitted).
- `nllb_code("auto")` → `TranslationError("unsupported_language")` — NLLB has
  no language detection.

Built-in languages: en, hi, ta, te, ml, kn, es, fr, de, pt, ja, ko, zh, ar, ru.

Add a language in three ways:
1. edit `LANGUAGES` in `languages.py`;
2. `register_language(Language(...))` at runtime;
3. set `TRANSLATION_EXTRA_LANGUAGES` (JSON list) in `.env`.

```
TRANSLATION_EXTRA_LANGUAGES=[{"iso_code":"mr","display_name":"Marathi","nllb_code":"mar_Deva"}]
```

## Cloud provider

`backend/app/services/translation/cloud_provider.py` calls the Google Cloud
Translation v2 REST endpoint directly with httpx (no SDK):

- POST `{cloud_translation_endpoint}` (default
  `https://translation.googleapis.com/language/translate/v2`)
- `?key={CLOUD_TRANSLATION_API_KEY}`,
  body `{"q": text, "target": cloud_code, "format": "text"[, "source": …]}`
- `source` omitted when the source language is `auto`.

Failure codes (all `TranslationError`):

| Code | Trigger |
|---|---|
| `cloud_config` | provider name ≠ `google`, or API key missing |
| `cloud_connection` | httpx network/transport error |
| `cloud_translation_error` | HTTP ≥ 400 or malformed response body |

Blank text short-circuits to an empty translation without a network call.
`cloud_translation_provider_name` accepts `google`, `deepl`, `azure` but only
`google` is wired; anything else fails with `cloud_config`.

## NLLB provider

`backend/app/services/translation/nllb_provider.py` loads
`facebook/nllb-200-distilled-600M` (default, overridable via `NLLB_MODEL_NAME`)
**lazily** on first use, off the event loop:

- `warm_up()` / first `translate()` acquire an `asyncio.Lock` and load the
  model in a thread (`asyncio.to_thread(self._load_model)`);
- generation runs in `_translate_engine(...)` in a thread with
  `forced_bos_token_id` set to the target FLORES token;
- if torch/transformers are missing (`ImportError`) or the model fails to
  load, `translate()` raises `TranslationError("nllb_model_unavailable")`.

**Install note.** The heavy dependencies (torch, transformers, sentencepiece)
live in the `offline` extra and only install cleanly on Python 3.11/3.12:

```
uv sync --extra offline   # on a Python 3.11/3.12 interpreter
```

On the current Python 3.14 runtime the provider is exercised entirely through
tests that monkeypatch `_load_model` / `_translate_engine`; a real model run
requires the `offline` extra.

## Transport integration

`backend/app/websocket/translate_stream.py`:

- `Session.translation_queue` — ordered `asyncio.Queue` of
  `(segment_id, text)` pairs for finalized utterances;
- `Session.translation_task` — one worker per session, started in
  `apply_config`, torn down in `stop()`/re-configuration;
- `_run_asr` enqueues only `segment.is_final` items (after the transcript +
  `asr_ms` latency events are sent);
- `_run_translation` sends a `translation` event plus a `latency` event with
  `translation_ms`; a failure sends `error { code: "translation_failed" }`
  and moves on.

Per-segment client event order:

```
partial_transcript → final_transcript → latency(asr_ms) → translation → latency(translation_ms)
```

## Latency measurement

`_run_translation` times the provider call with `time.monotonic()` and reports
`translation_ms` in a `latency` event. The frontend `LatencyIndicator` shows
the most specific metric available: `translation_ms` → `asr_ms` →
`end_to_end_ms`.

## Frontend

- `useTranslatorSession.ts` — `translation` events update the latest +
  history panels; `error` with code `translation_failed` is **non-fatal**
  (session status unchanged).
- `LatencyIndicator.tsx` — dev-only pill showing Translation/ASR latency.

## Testing

- `tests/test_languages.py` — registry mapping, `auto` semantics, unknown
  language rejection, runtime registration.
- `tests/test_translation_providers.py` — cloud provider against
  `httpx.MockTransport` (no network), NLLB via monkeypatched
  `_load_model`/`_translate_engine`, hybrid fallback and dual-failure, factory
  modes.
- `tests/test_websocket.py` — finals-only translation, in-order delivery,
  per-session languages, non-fatal `translation_failed`, `translation_ms`.

## Files

- `backend/app/services/translation/base.py` — `TranslationProvider`,
  `TranslationError`.
- `backend/app/services/translation/languages.py` — registry.
- `backend/app/services/translation/cloud_provider.py`, `nllb_provider.py`,
  `hybrid_provider.py`, `__init__.py` (factory).
- `backend/app/websocket/translate_stream.py` — queue/worker integration.
- `backend/app/config.py` — `translation_provider`, `cloud_translation_*`,
  `translation_extra_languages`, `nllb_*` settings.
- `frontend/src/hooks/useTranslatorSession.ts`,
  `frontend/src/components/LatencyIndicator/LatencyIndicator.tsx`.
