import type { ConnectionState, SessionConfiguration } from "../../types"
import type { StreamingClient, StreamingClientHandlers } from "./types"
import type { VADEvent } from "../vad/types"

const DEFAULT_CONFIGURATION: SessionConfiguration = {
  session_id: "mock-session",
  source_language: "en",
  target_language: "es",
  audio_source: "microphone",
  sample_rate: 16_000,
  encoding: "linear16",
}

export class MockStreamingClient implements StreamingClient {
  private readonly handlers: StreamingClientHandlers
  private timers = new Set<number>()
  private stopped = true
  private sessionId = "mock-session"
  private configuration: SessionConfiguration = DEFAULT_CONFIGURATION
  private scripted = 0

  constructor(handlers: StreamingClientHandlers) {
    this.handlers = handlers
  }

  get isOpen(): boolean {
    return !this.stopped
  }

  connect(): void {
    if (!this.stopped) return
    this.stopped = false
    this.setConnectionState("connecting")
    const id = window.setTimeout(() => {
      this.timers.delete(id)
      if (this.stopped) return
      this.setConnectionState("connected")
      this.handlers.onEvent({
        type: "session_started",
        session_id: this.sessionId,
        configuration: {
          ...this.configuration,
          session_id: this.sessionId,
        },
      })
      this.playScript()
    }, 300)
    this.timers.add(id)
  }

  private playScript(): void {
    const lines: Array<[number, string, string]> = [
      [1000, "Hello, how are you today?", "Hola, ¿cómo estás hoy?"],
      [4000, "The weather is lovely this morning.", "Hoy hace un clima precioso."],
    ]
    for (const [offsetMs, source, translation] of lines) {
      const segmentId = `mock-segment-${this.scripted}`
      this.scripted += 1
      const id = window.setTimeout(() => {
        this.timers.delete(id)
        if (this.stopped) return
        const sessionId = this.sessionId
        this.handlers.onEvent({
          type: "final_transcript",
          session_id: sessionId,
          segment_id: segmentId,
          text: source,
          is_final: true,
          confidence: 1,
        })
        this.handlers.onEvent({
          type: "pending_translation",
          session_id: sessionId,
          segment_id: segmentId,
          source_text: source,
          source_language: this.configuration.source_language,
          target_language: this.configuration.target_language,
        })
        this.handlers.onEvent({
          type: "translation",
          session_id: sessionId,
          segment_id: segmentId,
          source_text: source,
          translated_text: translation,
          source_language: this.configuration.source_language,
          target_language: this.configuration.target_language,
          is_final: true,
          provider: "mock",
        })
      }, offsetMs)
      this.timers.add(id)
    }
  }

  sendStartSession(sessionId: string): void {
    this.sessionId = sessionId
  }

  sendConfiguration(config: SessionConfiguration): void {
    this.configuration = { ...this.configuration, ...config }
  }

  sendAudio(_bytes: Uint8Array): void {
    return
  }

  sendVADEvent(_event: VADEvent): void {
    return
  }

  sendStopSession(_sessionId: string): void {
    return
  }

  close(): void {
    this.stopped = true
    this.timers.forEach((id) => window.clearTimeout(id))
    this.timers.clear()
  }

  private setConnectionState(state: ConnectionState): void {
    this.handlers.onStateChange(state)
  }
}
