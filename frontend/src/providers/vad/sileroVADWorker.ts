/**
 * Silero VAD inference worker.
 *
 * Runs onnxruntime-web (WASM) off the main thread so model inference never
 * blocks the audio streaming path. The AudioWorklet keeps resampling/streaming
 * PCM16; it also posts 512-sample Float32 windows here, which are fed through
 * the Silero VAD v5 model (a causal, fixed-window classifier) to produce the
 * five VAD lifecycle events.
 *
 * Model contract (Silero VAD v5, verified against utils_vad.py):
 *   - input  : float32 [1, 576]   -> [64 context samples | 512 window]
 *   - state  : float32 [2, 1, 128] -> LSTM-style recurrent state (zeros start)
 *   - sr     : int64  [1]          -> 16000
 *   - output : float32 [1, 1]      -> speech probability
 *   - stateN : float32 [2, 1, 128] -> next recurrent state
 * The context is the last 64 samples of the previous window and is required
 * for correct probabilities.
 *
 * Frames that arrive before the model is ready are buffered (bounded) and
 * replayed once loaded, so speech at startup is not lost.
 */
import * as ort from "onnxruntime-web/wasm"

import type { VADConfig, VADEvent, VADEventType } from "./types"
import { DEFAULT_VAD_CONFIG } from "./types"

type WorkerInMessage =
  | { type: "init"; config: VADConfig }
  | { type: "frame"; samples: Float32Array }
  | { type: "setConfig"; config: Partial<VADConfig> }
  | { type: "reset" }

type WorkerOutMessage =
  | { type: "ready"; loadMs: number }
  | { type: "event"; event: VADEvent }
  | { type: "prob"; probability: number }
  | { type: "error"; message: string }

const MAX_PENDING_FRAMES = 150
const PROB_REPORT_INTERVAL_MS = 120
const MODEL_STATE_CHANNELS = 2
const MODEL_STATE_DEPTH = 128

const isCrossOriginIsolated =
  (globalThis as { crossOriginIsolated?: boolean }).crossOriginIsolated === true

ort.env.wasm.wasmPaths = "/vendor/onnx/"
// The threaded build creates pthread workers that receive the SharedArrayBuffer
// via postMessage. Sending a SharedArrayBuffer is only allowed inside a
// cross-origin-isolated agent, so without COOP/COEP we must stay on one thread
// (creation of shared memory itself is always permitted).
ort.env.wasm.numThreads = isCrossOriginIsolated
  ? (navigator.hardwareConcurrency > 1 ? 2 : 1)
  : 1

let config: VADConfig = DEFAULT_VAD_CONFIG
let session: ort.InferenceSession | null = null
let loaded = false

let modelState: ort.Tensor | null = null
let context: Float32Array = new Float32Array(config.contextSize)
let srTensor: ort.Tensor | null = null

let speechState: "idle" | "speaking" | "pending" | "silence" = "idle"
let frameIndex = 0
let lastSpeechFrame = 0
let lastHeartbeatAt = 0
let lastProbAt = 0

const pending: Float32Array[] = []
let draining = false
let chain: Promise<void> = Promise.resolve()

self.onmessage = (event: MessageEvent<WorkerInMessage>) => {
  const message = event.data
  switch (message.type) {
    case "init":
      void initialize(message.config)
      break
    case "frame":
      queueFrame(message.samples)
      break
    case "setConfig":
      config = { ...config, ...message.config }
      break
    case "reset":
      resetState()
      break
  }
}

function post(message: WorkerOutMessage): void {
  self.postMessage(message)
}

async function initialize(nextConfig: VADConfig): Promise<void> {
  config = { ...nextConfig }
  const started = Date.now()
  try {
    session = await createSession()
    loaded = true
    resetState()
    post({ type: "ready", loadMs: Date.now() - started })
    drainQueue()
  } catch (cause) {
    post({
      type: "error",
      message: cause instanceof Error ? cause.message : String(cause),
    })
  }
}

async function createSession(): Promise<ort.InferenceSession> {
  const urls = [config.modelUrl, ...config.modelFallbackUrls]
  let lastError: Error | null = null
  for (const url of urls) {
    try {
      const response = await fetch(url)
      if (!response.ok) {
        lastError = new Error(`VAD model fetch failed (HTTP ${response.status}): ${url}`)
        continue
      }
      const buffer = await response.arrayBuffer()
      return await ort.InferenceSession.create(buffer, {
        executionProviders: ["wasm"],
        graphOptimizationLevel: "all",
      })
    } catch (cause) {
      lastError = cause instanceof Error ? cause : new Error(String(cause))
    }
  }
  throw lastError ?? new Error("No VAD model source configured")
}

function resetState(): void {
  modelState = new ort.Tensor(
    "float32",
    new Float32Array(MODEL_STATE_CHANNELS * 1 * MODEL_STATE_DEPTH),
    [MODEL_STATE_CHANNELS, 1, MODEL_STATE_DEPTH],
  )
  context = new Float32Array(config.contextSize)
  srTensor = null
  speechState = "idle"
  frameIndex = 0
  lastSpeechFrame = 0
  lastHeartbeatAt = 0
  lastProbAt = 0
  pending.length = 0
}

function queueFrame(samples: Float32Array): void {
  if (!loaded) {
    if (pending.length < MAX_PENDING_FRAMES) pending.push(samples)
    return
  }
  pending.push(samples)
  drainQueue()
}

function drainQueue(): void {
  if (draining || !loaded) return
  draining = true
  chain = chain
    .then(async () => {
      while (pending.length > 0) {
        const samples = pending.shift()
        if (samples) await runFrame(samples)
      }
      draining = false
    })
    .catch((cause: unknown) => {
      draining = false
      post({
        type: "error",
        message: cause instanceof Error ? cause.message : String(cause),
      })
    })
}

async function runFrame(samples: Float32Array): Promise<void> {
  if (!session || !modelState) return
  const windowSize = config.windowSize
  const contextSize = config.contextSize
  if (samples.length !== windowSize) return

  const inputData = new Float32Array(contextSize + windowSize)
  inputData.set(context, 0)
  inputData.set(samples, contextSize)

  if (!srTensor) {
    srTensor = new ort.Tensor("int64", new BigInt64Array([BigInt(config.sampleRate)]), [1])
  }

  const results = await session.run({
    input: new ort.Tensor("float32", inputData, [1, contextSize + windowSize]),
    state: modelState,
    sr: srTensor,
  })
  const probability = Number((results.output as ort.Tensor).data[0])
  const nextState = results.stateN as ort.Tensor

  context.set(samples.subarray(windowSize - contextSize, windowSize))
  modelState = nextState

  const nowMs = Date.now()
  frameIndex += 1
  evaluateSpeech(probability, nowMs)

  if (nowMs - lastProbAt >= PROB_REPORT_INTERVAL_MS) {
    lastProbAt = nowMs
    post({ type: "prob", probability })
  }
}

function frameDurationMs(): number {
  return (config.windowSize / config.sampleRate) * 1000
}

/**
 * Silero probabilities swing frame to frame, so use a hysteresis: speech onset
 * requires the configured threshold; leaving the speaking state requires the
 * threshold minus a fixed 0.15 margin (same rule as the reference VADIterator).
 */
function evaluateSpeech(probability: number, nowMs: number): void {
  const frameMs = frameDurationMs()
  const negativeThreshold = Math.max(0.1, config.speechProbThreshold - 0.15)
  const silentForMs = (frameIndex - lastSpeechFrame) * frameMs

  switch (speechState) {
    case "idle":
      if (probability >= config.speechProbThreshold) {
        speechState = "speaking"
        lastSpeechFrame = frameIndex
        emitEvent("speech_started", probability, nowMs)
      }
      break
    case "speaking":
      if (probability >= negativeThreshold) {
        lastSpeechFrame = frameIndex
      } else if (silentForMs >= config.hangoverMs) {
        speechState = "pending"
        emitEvent("silence_started", probability, nowMs)
      }
      break
    case "pending":
      if (probability >= config.speechProbThreshold) {
        speechState = "speaking"
        lastSpeechFrame = frameIndex
        emitEvent("speech_resumed", probability, nowMs)
      } else if (silentForMs >= config.silenceThresholdMs) {
        speechState = "silence"
        emitEvent("silence_detected", probability, nowMs, Math.round(silentForMs))
      }
      break
    case "silence":
      if (probability >= config.speechProbThreshold) {
        speechState = "speaking"
        lastSpeechFrame = frameIndex
        emitEvent("speech_started", probability, nowMs)
      }
      break
  }

  if (speechState === "speaking" && nowMs - lastHeartbeatAt >= config.speakingHeartbeatMs) {
    lastHeartbeatAt = nowMs
    emitEvent("speaking", probability, nowMs)
  }
}

function emitEvent(
  type: VADEventType,
  probability: number,
  nowMs: number,
  durationMs?: number,
): void {
  const event: VADEvent = { type, timestamp: nowMs, probability }
  if (durationMs !== undefined) event.durationMs = durationMs
  post({ type: "event", event })
}
