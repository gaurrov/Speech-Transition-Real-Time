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
    }, 300)
    this.timers.add(id)
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
