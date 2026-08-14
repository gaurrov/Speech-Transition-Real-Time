import type {
  ClientMessage,
  ConnectionState,
  ServerEvent,
  SessionConfiguration,
} from "../types"
import type { StreamingClient, StreamingClientHandlers } from "../providers/streaming/types"
import type { VADEvent } from "../providers/vad/types"

const WS_PATH = "/ws/translate"
const MAX_RECONNECT_ATTEMPTS = 5
const RECONNECT_BASE_DELAY_MS = 500

function wsUrl(): string {
  const host = import.meta.env.VITE_BACKEND_HOST ?? "localhost:8000"
  const useTls = import.meta.env.VITE_BACKEND_USE_TLS === "true"
  const scheme = useTls ? "wss" : "ws"
  return `${scheme}://${host}${WS_PATH}`
}

export class TranslatorClient implements StreamingClient {
  private socket: WebSocket | null = null
  private pending: ClientMessage[] = []
  private explicitlyClosed = false
  private reconnectAttempts = 0
  private reconnectTimer: number | null = null
  private startSessionId: string | null = null
  private configuration: SessionConfiguration | null = null

  constructor(private readonly handlers: StreamingClientHandlers) {}

  get isOpen(): boolean {
    return this.socket?.readyState === WebSocket.OPEN
  }

  connect(): void {
    if (this.socket) return
    this.explicitlyClosed = false
    this.setState("connecting")
    this.openSocket()
  }

  sendStartSession(sessionId: string): void {
    this.startSessionId = sessionId
    this.queue({ type: "start_session", session_id: sessionId })
  }

  sendConfiguration(config: SessionConfiguration): void {
    this.configuration = config
    this.queue({ type: "session_configuration", ...config })
  }

  sendAudio(bytes: Uint8Array): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(bytes)
    }
  }

  sendVADEvent(event: VADEvent): void {
    if (this.socket?.readyState !== WebSocket.OPEN || !this.startSessionId) return
    const message: ClientMessage = {
      type: "vad_event",
      session_id: this.startSessionId,
      event: event.type,
      timestamp_ms: event.timestamp,
    }
    if (event.durationMs !== undefined) message.duration_ms = event.durationMs
    if (event.probability !== undefined) message.probability = event.probability
    this.sendJson(message)
  }

  sendStopSession(sessionId: string): void {
    this.queue({ type: "stop_session", session_id: sessionId })
  }

  close(): void {
    this.explicitlyClosed = true
    this.stopReconnect()
    this.pending = []
    if (this.socket) {
      this.socket.onclose = null
      this.socket.close()
      this.socket = null
    }
    this.setState("idle")
  }

  private openSocket(): void {
    const socket = new WebSocket(wsUrl())
    this.socket = socket
    socket.binaryType = "arraybuffer"

    socket.onopen = () => {
      this.reconnectAttempts = 0
      if (this.startSessionId) {
        this.pending.unshift({ type: "start_session", session_id: this.startSessionId })
      }
      if (this.configuration) {
        this.pending.push({ type: "session_configuration", ...this.configuration })
      }
      this.flushQueue()
      this.setState("connected")
    }

    socket.onmessage = (event: MessageEvent) => {
      if (typeof event.data !== "string") return
      try {
        const data = JSON.parse(event.data) as ServerEvent
        this.handlers.onEvent(data)
      } catch {
        this.handlers.onError("Received a malformed message from the server")
      }
    }

    socket.onerror = () => {
      this.handlers.onError("WebSocket connection error")
    }

    socket.onclose = () => {
      if (this.socket !== socket) return
      this.socket = null
      if (this.explicitlyClosed) {
        this.setState("disconnected")
        return
      }
      this.scheduleReconnect()
    }
  }

  private queue(message: ClientMessage): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.sendJson(message)
      return
    }
    this.pending.push(message)
  }

  private flushQueue(): void {
    const messages = this.pending
    this.pending = []
    for (const message of messages) {
      this.sendJson(message)
    }
  }

  private scheduleReconnect(): void {
    if (this.explicitlyClosed) return
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      this.setState("disconnected")
      this.handlers.onError("Connection lost. Reconnect attempts exhausted.")
      return
    }
    this.setState("reconnecting")
    const delay = RECONNECT_BASE_DELAY_MS * 2 ** this.reconnectAttempts
    this.reconnectAttempts += 1
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      if (this.explicitlyClosed) return
      this.setState("reconnecting")
      this.openSocket()
    }, delay)
  }

  private stopReconnect(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  private sendJson(payload: ClientMessage): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload))
    }
  }

  private setState(state: ConnectionState): void {
    this.handlers.onStateChange(state)
  }
}
