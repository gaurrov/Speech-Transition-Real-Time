import { useCallback, useEffect, useRef, useState } from "react"
import { AudioSourceError, MicrophoneAudioSource, type AudioSource } from "../providers/audio/sources"
import { SileroVADProvider } from "../providers/vad/sileroVADProvider"
import type { VADConfig, VADEvent, VADStatus } from "../providers/vad/types"
import { DEFAULT_VAD_CONFIG } from "../providers/vad/types"

export interface UseAudioCaptureOptions {
  onChunk?: (bytes: Uint8Array) => void
  targetSampleRate?: number
  chunkSizeMs?: number
  /** Enable client-side Silero VAD. Defaults to true. */
  vad?: boolean
  /** Initial VAD configuration overrides (silence threshold, etc.). */
  vadConfig?: Partial<VADConfig>
  /** Called for every VAD lifecycle event produced by the provider. */
  onVADEvent?: (event: VADEvent) => void
}

interface WorkletMessage {
  type: string
  buffer?: ArrayBuffer
  active?: boolean
  samples?: Float32Array
}

interface WorkletConfig {
  type: "configure"
  outputSampleRate: number
  chunkSamples: number
  speechThreshold: number
  hangoverMs: number
  vadEnabled: boolean
  vadWindowSize: number
}

const DEFAULT_TARGET_SAMPLE_RATE = 16_000
const DEFAULT_CHUNK_SIZE_MS = 100
const ACTIVITY_THRESHOLD = 0.012
const ACTIVITY_HANGOVER_MS = 350

function captureErrorMessage(cause: unknown): string {
  if (cause instanceof AudioSourceError) return cause.message
  if (cause instanceof DOMException) {
    switch (cause.name) {
      case "NotAllowedError":
        return "Audio capture permission was denied. Allow access and try again."
      case "NotFoundError":
        return "No audio source was found for this selection."
      case "NotReadableError":
        return "The audio source is in use by another application or cannot be read."
      default:
        return cause.message || "Unable to start audio capture."
    }
  }
  return cause instanceof Error ? cause.message : "Unable to start audio capture."
}

function audioContextCtor(): typeof AudioContext {
  return (
    window.AudioContext ??
    (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
  )
}

export function useAudioCapture({
  onChunk,
  targetSampleRate = DEFAULT_TARGET_SAMPLE_RATE,
  chunkSizeMs = DEFAULT_CHUNK_SIZE_MS,
  vad = true,
  vadConfig,
  onVADEvent,
}: UseAudioCaptureOptions = {}) {
  const [error, setError] = useState<string | null>(null)
  const [isCapturing, setIsCapturing] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [activityAvailable, setActivityAvailable] = useState(false)
  const [sampleRate, setSampleRate] = useState<number | null>(null)
  const [chunkSizeBytes, setChunkSizeBytes] = useState(
    2 * Math.max(1, Math.round((targetSampleRate * chunkSizeMs) / 1000)),
  )
  const [chunksPerSecond, setChunksPerSecond] = useState(0)
  const [bytesSent, setBytesSent] = useState(0)
  const [vadStatus, setVadStatus] = useState<VADStatus>("idle")
  const [vadReady, setVadReady] = useState(false)
  const [vadError, setVadError] = useState<string | null>(null)
  const [vadProbability, setVadProbability] = useState<number | null>(null)

  const onChunkRef = useRef(onChunk)
  onChunkRef.current = onChunk
  const targetSampleRateRef = useRef(targetSampleRate)
  targetSampleRateRef.current = targetSampleRate
  const chunkSizeMsRef = useRef(chunkSizeMs)
  chunkSizeMsRef.current = chunkSizeMs
  const vadEnabledRef = useRef(vad)
  const vadConfigRef = useRef<Partial<VADConfig>>(vadConfig ?? {})
  const onVADEventRef = useRef(onVADEvent)
  onVADEventRef.current = onVADEvent

  const streamRef = useRef<MediaStream | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const muteGainRef = useRef<GainNode | null>(null)
  const vadProviderRef = useRef<SileroVADProvider | null>(null)
  const capturingRef = useRef(false)
  const chunksRef = useRef(0)
  const bytesSentRef = useRef(0)
  const lastStatsCountRef = useRef(0)
  const statsTimerRef = useRef<number | null>(null)

  const teardown = useCallback((updateState: boolean) => {
    if (statsTimerRef.current !== null) {
      window.clearInterval(statsTimerRef.current)
      statsTimerRef.current = null
    }
    if (workletNodeRef.current) {
      workletNodeRef.current.port.onmessage = null
      workletNodeRef.current.port.close()
      workletNodeRef.current.disconnect()
      workletNodeRef.current = null
    }
    sourceNodeRef.current?.disconnect()
    sourceNodeRef.current = null
    muteGainRef.current?.disconnect()
    muteGainRef.current = null

    const context = audioContextRef.current
    audioContextRef.current = null
    if (context) {
      void context.close().catch(() => undefined)
    }

    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null

    capturingRef.current = false
    chunksRef.current = 0
    bytesSentRef.current = 0
    lastStatsCountRef.current = 0
    vadProviderRef.current?.dispose()
    vadProviderRef.current = null
    setChunksPerSecond(0)
    setBytesSent(0)
    setIsSpeaking(false)
    setActivityAvailable(false)
    setSampleRate(null)
    setVadStatus("idle")
    setVadReady(false)
    setVadError(null)
    setVadProbability(null)
    if (updateState) {
      setIsCapturing(false)
    }
  }, [])

  const start = useCallback(
    async (source?: AudioSource): Promise<boolean> => {
      if (capturingRef.current) return true
      setError(null)

      const audioSource = source ?? new MicrophoneAudioSource()
      let mediaStream: MediaStream
      try {
        mediaStream = await audioSource.acquire()
      } catch (cause) {
        setError(captureErrorMessage(cause))
        return false
      }
      streamRef.current = mediaStream

      const Ctor = audioContextCtor()
      if (!Ctor) {
        teardown(true)
        setError("Web Audio is not supported in this browser.")
        return false
      }

      let audioContext: AudioContext | null = null
      try {
        audioContext = new Ctor({ sampleRate: targetSampleRateRef.current })
      } catch {
        try {
          audioContext = new Ctor()
        } catch {
          audioContext = null
        }
      }
      if (!audioContext) {
        teardown(true)
        setError("Web Audio is not supported in this browser.")
        return false
      }
      audioContextRef.current = audioContext

      try {
        if (audioContext.state === "suspended") {
          await audioContext.resume()
        }
        await audioContext.audioWorklet.addModule(
          new URL("../audio/pcmCaptureWorklet.js", import.meta.url).href,
        )
      } catch (cause) {
        teardown(true)
        setError(cause instanceof Error ? cause.message : "Unable to start audio capture")
        return false
      }

      const chunkSamples = Math.max(
        1,
        Math.round((targetSampleRateRef.current * chunkSizeMsRef.current) / 1000),
      )
      const config: WorkletConfig = {
        type: "configure",
        outputSampleRate: targetSampleRateRef.current,
        chunkSamples,
        speechThreshold: ACTIVITY_THRESHOLD,
        hangoverMs: ACTIVITY_HANGOVER_MS,
        vadEnabled: vadEnabledRef.current,
        vadWindowSize: DEFAULT_VAD_CONFIG.windowSize,
      }

      try {
        const node = new AudioWorkletNode(audioContext, "pcm-capture-processor", {
          numberOfInputs: 1,
          numberOfOutputs: 1,
          channelCount: 1,
          channelCountMode: "explicit",
          channelInterpretation: "speakers",
        })
        const muteGain = audioContext.createGain()
        muteGain.gain.value = 0
        const source = audioContext.createMediaStreamSource(mediaStream)

        source.connect(node)
        node.connect(muteGain)
        muteGain.connect(audioContext.destination)

        node.port.onmessage = (event: MessageEvent<WorkletMessage>) => {
          const message = event.data
          if (message.type === "audio" && message.buffer instanceof ArrayBuffer) {
            const bytes = new Uint8Array(message.buffer)
            bytesSentRef.current += bytes.byteLength
            chunksRef.current += 1
            onChunkRef.current?.(bytes)
          } else if (message.type === "activity") {
            setActivityAvailable(true)
            setIsSpeaking(message.active === true)
          } else if (message.type === "vad" && message.samples instanceof Float32Array) {
            vadProviderRef.current?.processFrame(message.samples)
          }
        }
        node.port.postMessage(config)

        if (vadEnabledRef.current) {
          const provider = new SileroVADProvider()
          vadProviderRef.current = provider
          provider.configure(vadConfigRef.current)
          // The Silero model emits a probability every VAD frame (~32 ms). Throttle
          // the React state update to ~4 Hz so the renderer is not re-rendered
          // tens of times per second just to show a dev-only diagnostic number.
          let lastProbStateAt = 0
          provider.onEvent((vadEvent) => {
            const now = performance.now()
            if (now - lastProbStateAt >= 250) {
              lastProbStateAt = now
              setVadProbability(vadEvent.probability)
            }
            onVADEventRef.current?.(vadEvent)
          })
          provider.onStateChange(setVadStatus)
          // Non-blocking: streaming starts immediately; the model loads in the
          // background and frames are buffered by the worker until it is ready.
          provider
            .start()
            .then(() => provider.init())
            .then(() => setVadReady(true))
            .catch((cause: unknown) => {
              setVadError(cause instanceof Error ? cause.message : String(cause))
            })
        }

        workletNodeRef.current = node
        sourceNodeRef.current = source
        muteGainRef.current = muteGain

        chunksRef.current = 0
        bytesSentRef.current = 0
        lastStatsCountRef.current = 0
        setSampleRate(audioContext.sampleRate)
        setChunkSizeBytes(chunkSamples * 2)

        capturingRef.current = true
        setIsCapturing(true)

        statsTimerRef.current = window.setInterval(() => {
          const chunks = chunksRef.current
          setChunksPerSecond(chunks - lastStatsCountRef.current)
          lastStatsCountRef.current = chunks
          setBytesSent(bytesSentRef.current)
        }, 1000)

        return true
      } catch (cause) {
        teardown(true)
        setError(cause instanceof Error ? cause.message : "Unable to start audio capture")
        return false
      }
    },
    [teardown],
  )

  const stop = useCallback(() => {
    teardown(true)
  }, [teardown])

  const setVADConfig = useCallback((partial: Partial<VADConfig>) => {
    vadConfigRef.current = { ...vadConfigRef.current, ...partial }
    vadProviderRef.current?.configure(partial)
  }, [])

  useEffect(
    () => () => {
      teardown(false)
    },
    [teardown],
  )

  return {
    error,
    isCapturing,
    isSpeaking,
    activityAvailable,
    sampleRate,
    chunkSizeBytes,
    chunksPerSecond,
    bytesSent,
    vadStatus,
    vadReady,
    vadError,
    vadProbability,
    vadEnabled: vadEnabledRef.current,
    setVADConfig,
    start,
    stop,
  }
}
