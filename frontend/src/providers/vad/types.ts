/**
 * Client-side voice activity detection (VAD) contract.
 *
 * The Silero VAD provider runs in a Web Worker so inference never blocks the
 * audio streaming path. The worklet keeps producing PCM16 chunks for the
 * network while the VAD worker consumes the same 16 kHz stream and emits the
 * five lifecycle events below.
 */

export type VADEventType =
  | "speech_started"
  | "speaking"
  | "silence_started"
  | "silence_detected"
  | "speech_resumed"

export interface VADEvent {
  type: VADEventType
  /** Epoch ms when the transition was detected. */
  timestamp: number
  /** Silero speech probability at the moment of the event (0..1). */
  probability: number
  /** Measured silence gap, set on `silence_detected`. */
  durationMs?: number
}

export type VADStatus =
  | "idle"
  | "loading"
  | "speaking"
  | "silence"
  | "error"

export interface VADConfig {
  /** ASR rate the worklet resamples to before feeding VAD. */
  sampleRate: number
  /** Silero processes fixed 30 ms windows: 512 samples @ 16 kHz. */
  windowSize: number
  /**
   * Silero v5 expects 64 samples of the previous window prepended to the
   * current one (context). The real model input is windowSize + contextSize.
   */
  contextSize: number
  /** Probability at which speech is considered to have started (0..1). */
  speechProbThreshold: number
  /**
   * After this much silence, `silence_started` fires and the UI shows
   * "Silence detected" even though the utterance may still be ongoing.
   */
  hangoverMs: number
  /**
   * An utterance boundary: once silence exceeds this (measured from the last
   * speech frame), `silence_detected` fires and later speech starts a new
   * utterance. Short pauses (e.g. 100 ms) never get this far.
   */
  silenceThresholdMs: number
  /** Cadence of the `speaking` heartbeat while speech is active. */
  speakingHeartbeatMs: number
  /** Same-origin model path (provisioned by scripts/setup-vad.mjs). */
  modelUrl: string
  /** CDN fallbacks tried when the same-origin model is missing. */
  modelFallbackUrls: string[]
}

export const DEFAULT_VAD_CONFIG: VADConfig = {
  sampleRate: 16_000,
  windowSize: 512,
  contextSize: 64,
  speechProbThreshold: 0.5,
  hangoverMs: 300,
  silenceThresholdMs: 600,
  speakingHeartbeatMs: 200,
  modelUrl: "/models/silero_vad.onnx",
  modelFallbackUrls: [
    "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx",
    "https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx",
  ],
}

export interface VADProvider {
  /** Begin (or resume) loading the model. Never blocks callers. */
  init(): Promise<void>
  /** Begin VAD processing of frames forwarded via processFrame(). */
  start(): Promise<void>
  /** Stop VAD processing and reset the internal state machine. */
  stop(): Promise<void>
  /** Release the underlying worker and drop all subscriptions. */
  dispose(): void
  /** Feed one contiguous Float32 window (windowSize samples @ sampleRate). */
  processFrame(samples: Float32Array): void
  /** Subscribe to VAD lifecycle events. Returns an unsubscribe function. */
  onEvent(callback: (event: VADEvent) => void): () => void
  /** Subscribe to provider status changes (loading/speaking/...). */
  onStateChange(callback: (status: VADStatus) => void): () => void
  /** Subscribe to throttled per-frame speech probabilities (diagnostics). */
  onProbability(callback: (probability: number) => void): () => void
  /** Apply partial config changes live (e.g. silence threshold). */
  configure(partial: Partial<VADConfig>): void
  readonly state: VADStatus
}
