import type {
  ConnectionState,
  ServerEvent,
  SessionStartRequest,
  SessionStatus,
} from "../../types"
import type { StreamingClient, StreamingClientHandlers } from "./types"

interface ScenarioUtterance {
  text: string
  translation: string
  refinement?: string
}

const SCENARIO: ScenarioUtterance[] = [
  {
    text: "Good morning everyone thanks for joining today's meeting",
    translation: "Buenos días a todos, gracias por unirse a la reunión de hoy.",
    refinement: "Good morning everyone, thanks for joining today's meeting.",
  },
  {
    text: "Let's review the roadmap for this quarter",
    translation: "Repasemos la hoja de ruta de este trimestre.",
  },
  {
    text: "We shipped the transcript feature and it's looking solid",
    translation: "Enviamos la función de transcripción y se ve muy sólida.",
  },
  {
    text: "Next up is the streaming translation pipeline",
    translation: "Lo siguiente es la canalización de traducción en streaming.",
  },
]

export class MockStreamingClient implements StreamingClient {
  private readonly handlers: StreamingClientHandlers
  private timers = new Set<number>()
  private stopped = true
  private sequence = 0
  private pendingSleep: (() => void) | null = null

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
    void this.run()
  }

  sendStart(_start: SessionStartRequest): void {
    return
  }

  sendSilence(_duration_ms: number): void {
    return
  }

  sendStop(): void {
    return
  }

  sendAudio(_bytes: Uint8Array): void {
    return
  }

  close(): void {
    this.stopped = true
    this.timers.forEach((id) => window.clearTimeout(id))
    this.timers.clear()
    this.pendingSleep?.()
    this.pendingSleep = null
  }

  private async run(): Promise<void> {
    await this.sleep(900)
    if (this.stopped) return
    this.setConnectionState("connected")
    this.setStatus("listening")
    this.emitStatus("Connected. Start speaking when ready.")

    await this.sleep(900)

    let pass = 0
    while (!this.stopped) {
      for (const utterance of SCENARIO) {
        await this.playUtterance(utterance)
        if (this.stopped) return
      }
      pass += 1
      if (pass === 1) {
        await this.simulateReconnect()
        if (this.stopped) return
      }
      await this.sleep(1400)
    }
  }

  private async playUtterance(utterance: ScenarioUtterance): Promise<void> {
    const segmentId = `seg-${this.sequence}`
    this.sequence += 1

    this.setStatus("speaking")

    const words = utterance.text.split(" ")
    const stepSize = Math.max(1, Math.ceil(words.length / 4))
    const partialCount = Math.ceil(words.length / stepSize)
    for (let i = 1; i <= partialCount; i += 1) {
      const text = words.slice(0, i * stepSize).join(" ")
      this.emitTranscript(segmentId, text, false)
      await this.sleep(360 + (i % 3) * 70)
      if (this.stopped) return
    }

    this.emitTranscript(segmentId, utterance.text, true)
    await this.sleep(300)
    if (this.stopped) return

    this.setStatus("silence")
    this.emitLatency(segmentId)
    await this.sleep(480)
    if (this.stopped) return

    this.setStatus("translating")

    const translationWords = utterance.translation.split(" ")
    const tStepSize = Math.max(1, Math.ceil(translationWords.length / 4))
    const tPartialCount = Math.ceil(translationWords.length / tStepSize)
    for (let i = 1; i <= tPartialCount; i += 1) {
      const text = translationWords.slice(0, i * tStepSize).join(" ")
      this.emitTranslation(segmentId, utterance.text, text, false)
      await this.sleep(240 + (i % 3) * 50)
      if (this.stopped) return
    }

    this.emitTranslation(segmentId, utterance.text, utterance.translation, true)

    if (utterance.refinement) {
      const refinedText = utterance.refinement
      this.schedule(() => {
        if (this.stopped) return
        this.emit({
          type: "refinement",
          segment_id: segmentId,
          refined_text: refinedText,
          changed: true,
        })
      }, 1500)
    }

    await this.sleep(600)
    if (this.stopped) return
    this.setStatus("listening")
  }

  private async simulateReconnect(): Promise<void> {
    this.setStatus("error")
    this.emitError("connection_lost", "Connection lost. Attempting to reconnect…")
    this.setConnectionState("reconnecting")
    await this.sleep(1500)
    if (this.stopped) return
    this.setConnectionState("connected")
    this.setStatus("listening")
    this.emitStatus("Reconnected successfully.")
  }

  private emit(event: ServerEvent): void {
    this.handlers.onEvent(event)
  }

  private setConnectionState(state: ConnectionState): void {
    this.handlers.onStateChange(state)
  }

  private setStatus(status: SessionStatus): void {
    this.emit({ type: "session_state", state: status })
  }

  private emitStatus(message: string): void {
    this.emit({ type: "status", message })
  }

  private emitError(code: string, message: string): void {
    this.emit({ type: "error", code, message })
  }

  private emitTranscript(
    segmentId: string,
    text: string,
    isFinal: boolean,
  ): void {
    this.emit({
      type: isFinal ? "transcript_final" : "transcript_partial",
      segment_id: segmentId,
      text,
      is_final: isFinal,
    })
  }

  private emitTranslation(
    segmentId: string,
    sourceText: string,
    translatedText: string,
    isFinal: boolean,
  ): void {
    this.emit({
      type: isFinal ? "translation_final" : "translation_partial",
      segment_id: segmentId,
      source_text: sourceText,
      translated_text: translatedText,
      source_language: "en",
      target_language: "es",
      is_final: isFinal,
      provider: "mock",
    })
  }

  private emitLatency(segmentId: string): void {
    const jitter = Math.floor(Math.random() * 80)
    this.emit({
      type: "latency",
      segment_id: segmentId,
      asr_ms: 180 + jitter,
      translation_ms: 110 + jitter / 2,
      end_to_end_ms: 290 + jitter,
    })
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      this.pendingSleep = resolve
      const id = window.setTimeout(() => {
        this.pendingSleep = null
        resolve()
      }, ms)
      this.timers.add(id)
    })
  }

  private schedule(fn: () => void, ms: number): void {
    const id = window.setTimeout(() => {
      this.timers.delete(id)
      fn()
    }, ms)
    this.timers.add(id)
  }
}
