import type { VADEventType } from "../providers/vad/types"

export type ConnectionState =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"

export type SessionStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "listening"
  | "speaking"
  | "silence"
  | "translating"
  | "reconnecting"
  | "error"
  | "disconnected"

export type SessionMode = "mock" | "live"

/** How the companion window lays out its content. */
export type WindowMode = "expanded" | "compact" | "overlay"

export type AudioEncoding = "linear16" | "opus"

export interface SessionConfiguration {
  session_id: string
  source_language: string
  target_language: string
  audio_source: string
  sample_rate: number
  encoding: AudioEncoding
}

export interface TranscriptSegment {
  segment_id: string
  text: string
  is_final: boolean
  start_ms?: number | null
  end_ms?: number | null
  confidence?: number | null
  refined?: boolean
}

export interface TranslationSegment {
  segment_id: string
  source_text: string
  translated_text: string
  source_language: string
  target_language: string
  is_final: boolean
  provider: string
}

export interface RefinementResult {
  segment_id: string
  refined_text: string
  changed: boolean
}

export interface LatencyReport {
  segment_id: string
  asr_ms?: number | null
  /** T3 - T2: backend audio content receipt -> ASR partial result. */
  asr_partial_ms?: number | null
  /** T4 - T2: backend audio content receipt -> ASR final result. */
  asr_final_ms?: number | null
  /** T6 - T5: translation request -> response (server measured). */
  translation_ms?: number | null
  /** Time spent on the async LLM refinement pass (separate from the live path). */
  refinement_ms?: number | null
  /** T6 - T2: server-side live-path end-to-end (ASR final + translation). */
  end_to_end_ms?: number | null
  /** T7 - T6 estimate: server send -> UI receipt (dev-only, client-computed). */
  ui_ms?: number | null
  /** T7 - T4': client receipt of final_transcript -> matching translation. */
  final_to_translation_ms?: number | null
  /** Client audio send -> backend ack round-trip (dev-only, client-computed). */
  network_ms?: number | null
  /** T7 - T0: composed from server end_to_end_ms + the client-observed UI gap. */
  speech_to_translation_ms?: number | null
}

export type ClientMessage =
  | { type: "start_session"; session_id?: string }
  | { type: "session_configuration" } & SessionConfiguration
  | { type: "audio_chunk"; session_id: string }
  | {
      type: "vad_event"
      session_id: string
      event: VADEventType
      timestamp_ms: number
      duration_ms?: number | null
      probability?: number | null
    }
  | { type: "stop_session"; session_id: string }

export type ServerEvent =
  | { type: "session_started"; session_id: string; configuration: SessionConfiguration }
  | { type: "speech_started"; session_id: string; timestamp_ms: number }
  | {
      type: "silence_detected"
      session_id: string
      timestamp_ms: number
      duration_ms?: number | null
    }
  | { type: "speech_resumed"; session_id: string; timestamp_ms: number }
  | {
      type: "audio_received"
      session_id: string
      chunks: number
      bytes: number
      audio_seconds: number
    }
  | ({ type: "partial_transcript" | "final_transcript"; session_id: string } & TranscriptSegment)
  | {
      type: "pending_translation"
      session_id: string
      segment_id: string
      source_text: string
      source_language: string
      target_language: string
    }
  | { type: "translation_skipped"; session_id: string; segment_id: string; reason?: string }
  | ({ type: "translation"; session_id: string } & TranslationSegment)
  | ({ type: "refined_transcript"; session_id: string } & RefinementResult)
  | ({ type: "latency"; session_id: string } & LatencyReport)
  | { type: "error"; session_id?: string; code: string; message: string }
  | { type: "session_stopped"; session_id: string; reason: string }

export interface LanguageOption {
  code: string
  label: string
}
