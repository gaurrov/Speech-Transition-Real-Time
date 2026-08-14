import type { ConnectionState, ServerEvent, SessionConfiguration } from "../../types"

export interface StreamingClientHandlers {
  onEvent: (event: ServerEvent) => void
  onStateChange: (state: ConnectionState) => void
  onError: (message: string) => void
}

export interface StreamingClient {
  connect(): void
  sendStartSession(sessionId: string): void
  sendConfiguration(config: SessionConfiguration): void
  sendAudio(bytes: Uint8Array): void
  sendStopSession(sessionId: string): void
  close(): void
  readonly isOpen: boolean
}
