import { useCallback, useRef, useState } from "react"
import { TranslatorClient } from "../lib/wsClient"
import { MockStreamingClient } from "../providers/streaming/mockStreamingClient"
import type { StreamingClient, StreamingClientHandlers } from "../providers/streaming/types"
import type {
  ConnectionState,
  LatencyReport,
  ServerEvent,
  SessionMode,
  SessionStartRequest,
  SessionStatus,
  TranslationSegment,
  TranscriptSegment,
} from "../types"

export interface UseTranslatorSessionOptions {
  mode?: SessionMode
}

export interface TranslatorSession {
  connectionState: ConnectionState
  status: SessionStatus
  transcriptSegments: TranscriptSegment[]
  partialText: string
  translationSegments: TranslationSegment[]
  latestTranslation: TranslationSegment | null
  latency: LatencyReport | null
  error: string | null
  start: (session: SessionStartRequest) => void
  stop: () => void
  dismissError: () => void
}

function createClient(
  mode: SessionMode,
  handlers: StreamingClientHandlers,
): StreamingClient {
  return mode === "live"
    ? new TranslatorClient(handlers)
    : new MockStreamingClient(handlers)
}

export function useTranslatorSession({
  mode = "mock",
}: UseTranslatorSessionOptions = {}): TranslatorSession {
  const [connectionState, setConnectionState] = useState<ConnectionState>("idle")
  const [status, setStatus] = useState<SessionStatus>("idle")
  const [transcriptSegments, setTranscriptSegments] = useState<TranscriptSegment[]>([])
  const [partialText, setPartialText] = useState("")
  const [translationSegments, setTranslationSegments] = useState<TranslationSegment[]>([])
  const [latestTranslation, setLatestTranslation] = useState<TranslationSegment | null>(null)
  const [latency, setLatency] = useState<LatencyReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const clientRef = useRef<StreamingClient | null>(null)
  const modeRef = useRef(mode)
  modeRef.current = mode

  const handleConnectionState = useCallback((state: ConnectionState) => {
    setConnectionState(state)
    if (state === "connecting" || state === "reconnecting") {
      setStatus(state === "reconnecting" ? "reconnecting" : "connecting")
    } else if (state === "connected") {
      setStatus((current) =>
        current === "idle" || current === "connecting" ? "connected" : current,
      )
    } else if (state === "disconnected") {
      setStatus((current) => (current === "error" ? "error" : "disconnected"))
    }
  }, [])

  const handleEvent = useCallback((event: ServerEvent) => {
    switch (event.type) {
      case "session_state":
        setStatus(event.state)
        if (event.state === "connected" || event.state === "listening") {
          setError(null)
        }
        break
      case "transcript_partial":
        setPartialText(event.text)
        break
      case "transcript_final": {
        const segment: TranscriptSegment = {
          segment_id: event.segment_id,
          text: event.text,
          is_final: true,
          start_ms: event.start_ms,
          end_ms: event.end_ms,
          confidence: event.confidence,
        }
        setTranscriptSegments((prev) => [
          ...prev.filter((existing) => existing.segment_id !== event.segment_id),
          segment,
        ])
        setPartialText("")
        break
      }
      case "translation_partial": {
        const segment: TranslationSegment = {
          segment_id: event.segment_id,
          source_text: event.source_text,
          translated_text: event.translated_text,
          source_language: event.source_language,
          target_language: event.target_language,
          is_final: event.is_final,
          provider: event.provider,
        }
        setLatestTranslation(segment)
        break
      }
      case "translation_final": {
        const segment: TranslationSegment = {
          segment_id: event.segment_id,
          source_text: event.source_text,
          translated_text: event.translated_text,
          source_language: event.source_language,
          target_language: event.target_language,
          is_final: true,
          provider: event.provider,
        }
        setLatestTranslation(segment)
        setTranslationSegments((prev) => [
          ...prev.filter((existing) => existing.segment_id !== event.segment_id),
          segment,
        ])
        break
      }
      case "refinement":
        setTranscriptSegments((prev) =>
          prev.map((segment) =>
            segment.segment_id === event.segment_id
              ? { ...segment, text: event.refined_text, refined: true }
              : segment,
          ),
        )
        break
      case "latency":
        setLatency(event)
        break
      case "error":
        setError(event.message)
        setStatus("error")
        break
      case "status":
        break
    }
  }, [])

  const start = useCallback(
    (session: SessionStartRequest) => {
      setError(null)
      setTranscriptSegments([])
      setTranslationSegments([])
      setPartialText("")
      setLatestTranslation(null)
      setLatency(null)
      setStatus("connecting")

      clientRef.current?.close()
      clientRef.current = createClient(modeRef.current, {
        onEvent: handleEvent,
        onStateChange: handleConnectionState,
        onError: (message) => setError(message),
      })
      clientRef.current.connect()
      clientRef.current.sendStart(session)
    },
    [handleEvent, handleConnectionState],
  )

  const stop = useCallback(() => {
    clientRef.current?.sendStop()
    clientRef.current?.close()
    clientRef.current = null
    setConnectionState("idle")
    setStatus("idle")
  }, [])

  const dismissError = useCallback(() => setError(null), [])

  return {
    connectionState,
    status,
    transcriptSegments,
    partialText,
    translationSegments,
    latestTranslation,
    latency,
    error,
    start,
    stop,
    dismissError,
  }
}
