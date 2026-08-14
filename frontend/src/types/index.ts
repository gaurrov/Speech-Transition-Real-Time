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

export interface SessionStartRequest {
  source_language: string
  target_language: string
  sample_rate: number
  encoding: "linear16" | "opus"
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
  translation_ms?: number | null
  end_to_end_ms?: number | null
}

export type ServerEvent =
  | ({ type: "transcript_partial" | "transcript_final" } & TranscriptSegment)
  | ({ type: "translation_partial" | "translation_final" } & TranslationSegment)
  | ({ type: "refinement" } & RefinementResult)
  | ({ type: "session_state"; state: SessionStatus })
  | ({ type: "status"; message: string })
  | ({ type: "error"; code: string; message: string })
  | ({ type: "latency" } & LatencyReport)

export interface LanguageOption {
  code: string
  label: string
}
