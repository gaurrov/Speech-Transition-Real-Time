import type { ConnectionState, ServerEvent, SessionStartRequest } from "../../types"

export interface StreamingClientHandlers {
  onEvent: (event: ServerEvent) => void
  onStateChange: (state: ConnectionState) => void
  onError: (message: string) => void
}

export interface StreamingClient {
  connect(): void
  sendStart(start: SessionStartRequest): void
  sendSilence(duration_ms: number): void
  sendStop(): void
  sendAudio(bytes: Uint8Array): void
  close(): void
  readonly isOpen: boolean
}
