import type { ConnectionState, ServerEvent, SessionStartRequest } from "../types"
import type { StreamingClient, StreamingClientHandlers } from "../providers/streaming/types"

const WS_PATH = "/ws/audio"

function wsUrl(): string {
  const host = import.meta.env.VITE_BACKEND_HOST ?? "localhost:8000"
  const useTls = import.meta.env.VITE_BACKEND_USE_TLS === "true"
  const scheme = useTls ? "wss" : "ws"
  return `${scheme}://${host}${WS_PATH}`
}

export class TranslatorClient implements StreamingClient {
  private socket: WebSocket | null = null

  constructor(private readonly handlers: StreamingClientHandlers) {}

  connect(): void {
    if (this.socket) return
    this.setState("connecting")
    const socket = new WebSocket(wsUrl())
    this.socket = socket

    socket.onopen = () => {
      this.setState("connected")
    }
    socket.onmessage = (event: MessageEvent<string>) => {
      try {
        const data = JSON.parse(event.data) as ServerEvent
        this.handlers.onEvent(data)
      } catch {
        this.handlers.onError("Received a malformed message from the server")
      }
    }
    socket.onerror = () => {
      this.handlers.onError("WebSocket error")
    }
    socket.onclose = () => {
      this.socket = null
      this.setState("disconnected")
    }
  }

  sendStart(start: SessionStartRequest): void {
    this.sendJson({ type: "start", ...start })
  }

  sendSilence(duration_ms: number): void {
    this.sendJson({ type: "silence", duration_ms })
  }

  sendStop(): void {
    this.sendJson({ type: "stop" })
  }

  sendAudio(bytes: Uint8Array): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(bytes)
    }
  }

  close(): void {
    this.socket?.close()
    this.socket = null
    this.setState("idle")
  }

  get isOpen(): boolean {
    return this.socket?.readyState === WebSocket.OPEN
  }

  private sendJson(payload: unknown): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload))
    }
  }

  private setState(state: ConnectionState): void {
    this.handlers.onStateChange(state)
  }
}
