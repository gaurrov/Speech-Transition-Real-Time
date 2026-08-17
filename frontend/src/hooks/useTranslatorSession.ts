import { useCallback, useEffect, useRef, useState } from "react"
import { TranslatorClient } from "../lib/wsClient"
import { MockStreamingClient } from "../providers/streaming/mockStreamingClient"
import type { StreamingClient, StreamingClientHandlers } from "../providers/streaming/types"
import type { VADEvent } from "../providers/vad/types"
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
  translationAvailable?: boolean | null
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
  /** Rolling per-utterance latency reports (dev-only panel; newest first). */
  latencyHistory: LatencyReport[]
  bytesReceived: number
  error: string | null
  start: (session: SessionConfiguration) => void
  sendAudio: (bytes: Uint8Array) => void
  sendVADEvent: (event: VADEvent) => void
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
  translationAvailable = null,
}: UseTranslatorSessionOptions = {}): TranslatorSession {
  const [connectionState, setConnectionState] = useState<ConnectionState>("idle")
  const [status, setStatus] = useState<SessionStatus>("idle")
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [transcriptSegments, setTranscriptSegments] = useState<TranscriptSegment[]>([])
  const [partialText, setPartialText] = useState("")
  const [translationSegments, setTranslationSegments] = useState<TranslationSegment[]>([])
  const [latestTranslation, setLatestTranslation] = useState<TranslationSegment | null>(null)
  const [latency, setLatency] = useState<LatencyReport | null>(null)
  const [latencyHistory, setLatencyHistory] = useState<LatencyReport[]>([])
  const [bytesReceived, setBytesReceived] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const clientRef = useRef<StreamingClient | null>(null)
  const sessionIdRef = useRef<string | null>(null)
  const modeRef = useRef(mode)
  modeRef.current = mode
  const translationAvailableRef = useRef(translationAvailable)
  translationAvailableRef.current = translationAvailable

  // Dev-only latency bookkeeping: final receipt time per segment (T4' client)
  // and the last audio chunk send time (T1) used for the network estimate.
  const finalReceivedAtRef = useRef(new Map<string, number>())
  const lastAudioSentAtRef = useRef<number>(0)
  const latestLatencyRef = useRef<LatencyReport | null>(null)

  useEffect(() => {
    sessionIdRef.current = sessionId
  }, [sessionId])

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
        finalReceivedAtRef.current.set(event.segment_id, performance.now())
        setTranscriptSegments((prev) => [
          ...prev.filter((existing) => existing.segment_id !== event.segment_id),
          segment,
        ])
        setPartialText("")
        setStatus("listening")
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
      case "latency": {
        const now = performance.now()
        // T7 - T4' (client): gap between receiving the final and its translation.
        let finalToTranslation: number | null = null
        if (event.translation_ms != null) {
          const finalAt = finalReceivedAtRef.current.get(event.segment_id)
          if (finalAt != null) {
            finalToTranslation = Math.max(0, now - finalAt)
            finalReceivedAtRef.current.delete(event.segment_id)
          }
        }
        // Speech -> translation composed from server end-to-end + the UI gap.
        const serverE2E = event.end_to_end_ms ?? null
        const speechToTranslation =
          serverE2E != null && finalToTranslation != null
            ? Math.round(serverE2E + finalToTranslation)
            : null
        const merged: LatencyReport = {
          ...event,
          final_to_translation_ms: finalToTranslation,
          speech_to_translation_ms: speechToTranslation,
        }
        latestLatencyRef.current = merged
        setLatency(merged)
        setLatencyHistory((prev) => {
          const next = [merged, ...prev].slice(0, 12)
          if (next.length > 1 && next[0].segment_id === next[1].segment_id) {
            next.splice(1, 1)
          }
          return next
        })
        break
      }
      case "audio_received":
        setBytesReceived(event.bytes)
        // Dev-only one-way network estimate: half the send->ack round-trip.
        if (lastAudioSentAtRef.current > 0) {
          const roundTrip = Math.max(0, performance.now() - lastAudioSentAtRef.current)
          if (latestLatencyRef.current) {
            const withNetwork = { ...latestLatencyRef.current, network_ms: Math.round(roundTrip / 2) }
            latestLatencyRef.current = withNetwork
            setLatency(withNetwork)
          }
        }
        break
      case "error": {
        // A translation failure is non-fatal: the session keeps running.
        // Suppress the per-utterance error when the standing banner already
        // explains why translation is unavailable.
        if (
          event.code === "translation_failed" &&
          translationAvailableRef.current === false
        ) {
          break
        }
        setError(event.message)
        setStatus("error")
        break
      }
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
      setLatencyHistory([])
      setBytesReceived(0)
      setStatus("connecting")
      setSessionId(session.session_id)
      finalReceivedAtRef.current.clear()
      lastAudioSentAtRef.current = 0
      latestLatencyRef.current = null

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
    lastAudioSentAtRef.current = performance.now()
    clientRef.current?.sendAudio(bytes)
  }, [])

  const sendVADEvent = useCallback((event: VADEvent) => {
    const speechOn =
      event.type === "speech_started" || event.type === "speaking" || event.type === "speech_resumed"
    const silenceOn = event.type === "silence_started" || event.type === "silence_detected"

    setStatus((current) => {
      if (
        current === "idle" ||
        current === "connecting" ||
        current === "reconnecting" ||
        current === "error" ||
        current === "disconnected"
      ) {
        return current
      }
      if (speechOn) {
        return current === "speaking" ? current : "speaking"
      }
      if (silenceOn && current === "speaking") {
        return "silence"
      }
      return current
    })

    if (sessionIdRef.current) {
      clientRef.current?.sendVADEvent(event)
    }
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
    latencyHistory,
    bytesReceived,
    error,
    start,
    sendAudio,
    sendVADEvent,
    stop,
    setSpeaking,
    dismissError,
  }
}
