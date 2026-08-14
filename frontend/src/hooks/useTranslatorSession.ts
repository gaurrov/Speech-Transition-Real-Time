import { useCallback, useRef, useState } from "react"
import { TranslatorClient } from "../lib/wsClient"
import { MockStreamingClient } from "../providers/streaming/mockStreamingClient"
import type { StreamingClient, StreamingClientHandlers } from "../providers/streaming/types"
import type {
  ConnectionState,
  LatencyReport,
  ServerEvent,
  SessionConfiguration,
  SessionMode,
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
  sessionId: string | null
  transcriptSegments: TranscriptSegment[]
  partialText: string
  translationSegments: TranslationSegment[]
  latestTranslation: TranslationSegment | null
  latency: LatencyReport | null
  bytesReceived: number
  error: string | null
  start: (session: SessionConfiguration) => void
  sendAudio: (bytes: Uint8Array) => void
  stop: () => void
  setSpeaking: (active: boolean) => void
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
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [transcriptSegments, setTranscriptSegments] = useState<TranscriptSegment[]>([])
  const [partialText, setPartialText] = useState("")
  const [translationSegments, setTranslationSegments] = useState<TranslationSegment[]>([])
  const [latestTranslation, setLatestTranslation] = useState<TranslationSegment | null>(null)
  const [latency, setLatency] = useState<LatencyReport | null>(null)
  const [bytesReceived, setBytesReceived] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const clientRef = useRef<StreamingClient | null>(null)
  const modeRef = useRef(mode)
  modeRef.current = mode

  const handleConnectionState = useCallback((state: ConnectionState) => {
    setConnectionState(state)
    switch (state) {
      case "connecting":
        setStatus("connecting")
        break
      case "reconnecting":
        setStatus("reconnecting")
        break
      case "connected":
        setStatus((current) =>
          current === "idle" || current === "connecting" || current === "reconnecting"
            ? "connected"
            : current,
        )
        break
      case "disconnected":
        setStatus((current) => (current === "error" ? "error" : "disconnected"))
        break
      default:
        break
    }
  }, [])

  const handleEvent = useCallback((event: ServerEvent) => {
    switch (event.type) {
      case "session_started":
        setStatus("listening")
        setError(null)
        break
      case "speech_started":
      case "speech_resumed":
        setStatus("speaking")
        break
      case "partial_transcript":
        setPartialText(event.text)
        setStatus("speaking")
        break
      case "silence_detected":
        setStatus("silence")
        break
      case "final_transcript": {
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
        setStatus("translating")
        break
      }
      case "translation": {
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
        if (event.is_final) {
          setTranslationSegments((prev) => [
            ...prev.filter((existing) => existing.segment_id !== event.segment_id),
            segment,
          ])
        }
        setStatus("listening")
        break
      }
      case "refined_transcript":
        setTranscriptSegments((prev) =>
          prev.map((segment) =>
            segment.segment_id === event.segment_id
              ? { ...segment, text: event.refined_text, refined: event.changed }
              : segment,
          ),
        )
        break
      case "latency":
        setLatency(event)
        break
      case "audio_received":
        setBytesReceived(event.bytes)
        break
      case "error":
        setError(event.message)
        setStatus("error")
        break
      case "session_stopped":
        break
    }
  }, [])

  const start = useCallback(
    (session: SessionConfiguration) => {
      setError(null)
      setTranscriptSegments([])
      setTranslationSegments([])
      setPartialText("")
      setLatestTranslation(null)
      setLatency(null)
      setBytesReceived(0)
      setStatus("connecting")
      setSessionId(session.session_id)

      clientRef.current?.close()
      const client = createClient(modeRef.current, {
        onEvent: handleEvent,
        onStateChange: handleConnectionState,
        onError: (message) => setError(message),
      })
      clientRef.current = client
      client.connect()
      client.sendStartSession(session.session_id)
      client.sendConfiguration(session)
    },
    [handleEvent, handleConnectionState],
  )

  const sendAudio = useCallback((bytes: Uint8Array) => {
    clientRef.current?.sendAudio(bytes)
  }, [])

  const stop = useCallback(() => {
    const client = clientRef.current
    if (client) {
      const currentSessionId = sessionId
      if (currentSessionId) client.sendStopSession(currentSessionId)
      client.close()
    }
    clientRef.current = null
    setSessionId(null)
    setConnectionState("idle")
    setStatus("idle")
  }, [sessionId])

  const dismissError = useCallback(() => setError(null), [])

  const setSpeaking = useCallback((active: boolean) => {
    setStatus((current) => {
      if (active && (current === "listening" || current === "connected" || current === "speaking")) {
        return "speaking"
      }
      if (!active && current === "speaking") {
        return "listening"
      }
      return current
    })
  }, [])

  return {
    connectionState,
    status,
    sessionId,
    transcriptSegments,
    partialText,
    translationSegments,
    latestTranslation,
    latency,
    bytesReceived,
    error,
    start,
    sendAudio,
    stop,
    setSpeaking,
    dismissError,
  }
}
