import type { VADConfig, VADEvent, VADProvider, VADStatus } from "./types"
import { DEFAULT_VAD_CONFIG } from "./types"

type WorkerOutMessage =
  | { type: "ready"; loadMs: number }
  | { type: "event"; event: VADEvent }
  | { type: "prob"; probability: number }
  | { type: "error"; message: string }

const SPEECH_EVENTS = new Set<VADEvent["type"]>([
  "speech_started",
  "speaking",
  "speech_resumed",
])

/**
 * Main-thread wrapper around the Silero VAD inference worker. Model loading
 * happens in the background (init() is fire-and-forget from the caller's
 * perspective), and frames are handed to the worker as soon as they arrive —
 * audio streaming never waits on the model.
 */
export class SileroVADProvider implements VADProvider {
  private worker: Worker | null = null
  private config: VADConfig = DEFAULT_VAD_CONFIG
  private initPromise: Promise<void> | null = null
  private started = false
  private status: VADStatus = "idle"
  private readonly eventHandlers = new Set<(event: VADEvent) => void>()
  private readonly stateHandlers = new Set<(status: VADStatus) => void>()
  private readonly probabilityHandlers = new Set<(probability: number) => void>()

  get state(): VADStatus {
    return this.status
  }

  init(): Promise<void> {
    if (!this.initPromise) {
      this.initPromise = this.load()
    }
    return this.initPromise
  }

  async start(): Promise<void> {
    this.started = true
    const worker = this.ensureWorker()
    worker.postMessage({ type: "reset" })
    this.init().catch(() => undefined)
  }

  async stop(): Promise<void> {
    this.started = false
    this.worker?.postMessage({ type: "reset" })
  }

  dispose(): void {
    this.started = false
    this.initPromise = null
    this.eventHandlers.clear()
    this.stateHandlers.clear()
    this.probabilityHandlers.clear()
    if (this.worker) {
      this.worker.onmessage = null
      this.worker.onerror = null
      this.worker.terminate()
      this.worker = null
    }
  }

  processFrame(samples: Float32Array): void {
    if (!this.started || !this.worker) return
    this.worker.postMessage({ type: "frame", samples }, [samples.buffer])
  }

  onEvent(callback: (event: VADEvent) => void): () => void {
    this.eventHandlers.add(callback)
    return () => this.eventHandlers.delete(callback)
  }

  onStateChange(callback: (status: VADStatus) => void): () => void {
    this.stateHandlers.add(callback)
    return () => this.stateHandlers.delete(callback)
  }

  onProbability(callback: (probability: number) => void): () => void {
    this.probabilityHandlers.add(callback)
    return () => this.probabilityHandlers.delete(callback)
  }

  configure(partial: Partial<VADConfig>): void {
    this.config = { ...this.config, ...partial }
    this.worker?.postMessage({ type: "setConfig", config: partial })
  }

  private ensureWorker(): Worker {
    if (this.worker) return this.worker
    const worker = new Worker(new URL("./sileroVADWorker.ts", import.meta.url), {
      type: "module",
    })
    worker.onmessage = (event: MessageEvent<WorkerOutMessage>) => {
      const message = event.data
      switch (message.type) {
        case "event":
          this.applyEventStatus(message.event)
          this.eventHandlers.forEach((handler) => handler(message.event))
          break
        case "prob":
          this.probabilityHandlers.forEach((handler) => handler(message.probability))
          break
        case "error":
          this.setStatus("error")
          break
        case "ready":
          break
      }
    }
    worker.onerror = () => {
      this.setStatus("error")
    }
    this.worker = worker
    return worker
  }

  private load(): Promise<void> {
    this.setStatus("loading")
    const worker = this.ensureWorker()
    return new Promise<void>((resolve, reject) => {
      const onMessage = (event: MessageEvent<WorkerOutMessage>) => {
        if (event.data.type === "ready") {
          cleanup()
          this.setStatus("idle")
          resolve()
        } else if (event.data.type === "error") {
          cleanup()
          this.setStatus("error")
          reject(new Error(event.data.message))
        }
      }
      const onError = () => {
        cleanup()
        this.setStatus("error")
        reject(new Error("VAD worker failed to start"))
      }
      const cleanup = () => {
        worker.removeEventListener("message", onMessage)
        worker.removeEventListener("error", onError)
      }
      worker.addEventListener("message", onMessage)
      worker.addEventListener("error", onError)
      worker.postMessage({ type: "init", config: this.config })
    })
  }

  private applyEventStatus(event: VADEvent): void {
    if (SPEECH_EVENTS.has(event.type)) {
      this.setStatus("speaking")
    } else if (event.type === "silence_started" || event.type === "silence_detected") {
      this.setStatus("silence")
    }
  }

  private setStatus(status: VADStatus): void {
    if (this.status === status) return
    this.status = status
    this.stateHandlers.forEach((handler) => handler(status))
  }
}
