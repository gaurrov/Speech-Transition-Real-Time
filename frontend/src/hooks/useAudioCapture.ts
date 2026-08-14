import { useCallback, useEffect, useRef, useState } from "react"

export interface UseAudioCaptureOptions {
  onChunk?: (bytes: Uint8Array) => void
  targetSampleRate?: number
  chunkSizeMs?: number
}

interface WorkletMessage {
  type: string
  buffer?: ArrayBuffer
  active?: boolean
}

interface WorkletConfig {
  type: "configure"
  outputSampleRate: number
  chunkSamples: number
  speechThreshold: number
  hangoverMs: number
}

const DEFAULT_TARGET_SAMPLE_RATE = 16_000
const DEFAULT_CHUNK_SIZE_MS = 100
const ACTIVITY_THRESHOLD = 0.012
const ACTIVITY_HANGOVER_MS = 350

function captureErrorMessage(cause: unknown): string {
  if (cause instanceof DOMException) {
    switch (cause.name) {
      case "NotAllowedError":
        return "Microphone permission was denied. Allow microphone access in your browser and try again."
      case "NotFoundError":
        return "No microphone was found on this device."
      case "NotReadableError":
        return "The microphone is in use by another application or cannot be read."
      case "OverconstrainedError":
        return "No microphone matching the requested settings was found."
      default:
        return cause.message || "Unable to access the microphone."
    }
  }
  return cause instanceof Error ? cause.message : "Unable to access the microphone."
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

  const onChunkRef = useRef(onChunk)
  onChunkRef.current = onChunk
  const targetSampleRateRef = useRef(targetSampleRate)
  targetSampleRateRef.current = targetSampleRate
  const chunkSizeMsRef = useRef(chunkSizeMs)
  chunkSizeMsRef.current = chunkSizeMs

  const streamRef = useRef<MediaStream | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const muteGainRef = useRef<GainNode | null>(null)
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
    setChunksPerSecond(0)
    setBytesSent(0)
    setIsSpeaking(false)
    setActivityAvailable(false)
    setSampleRate(null)
    if (updateState) {
      setIsCapturing(false)
    }
  }, [])

  const start = useCallback(async (): Promise<boolean> => {
    if (capturingRef.current) return true
    setError(null)

    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Microphone access is not supported in this browser.")
      return false
    }

    let mediaStream: MediaStream
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
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
        }
      }
      node.port.postMessage(config)

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
  }, [teardown])

  const stop = useCallback(() => {
    teardown(true)
  }, [teardown])

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
    start,
    stop,
  }
}
