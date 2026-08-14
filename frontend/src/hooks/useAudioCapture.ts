import { useCallback, useRef, useState } from "react"

export interface UseAudioCaptureOptions {
  simulate?: boolean
}

export function useAudioCapture({ simulate = false }: UseAudioCaptureOptions = {}) {
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isCapturing, setIsCapturing] = useState(false)
  const streamRef = useRef<MediaStream | null>(null)
  const simulateRef = useRef(simulate)
  simulateRef.current = simulate

  const start = useCallback(async (): Promise<boolean> => {
    setError(null)
    if (simulateRef.current) {
      setIsCapturing(true)
      return true
    }
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = mediaStream
      setStream(mediaStream)
      setIsCapturing(true)
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to access the microphone")
      return false
    }
  }, [])

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    setStream(null)
    setIsCapturing(false)
  }, [])

  return { stream, error, isCapturing, start, stop }
}
