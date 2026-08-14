import { useCallback, useEffect, useState } from "react"
import { AudioControls } from "./components/AudioControls"
import { DiagnosticsPanel } from "./components/DiagnosticsPanel"
import { ErrorBanner } from "./components/ErrorBanner"
import { Header } from "./components/Header"
import { LanguageControls } from "./components/LanguageControls"
import { SettingsModal } from "./components/SettingsModal"
import { TranscriptPanel } from "./components/TranscriptPanel"
import { TranslationPanel } from "./components/TranslationPanel"
import { AUDIO_SOURCES } from "./config/audioSources"
import { LANGUAGES, SOURCE_LANGUAGES } from "./config/languages"
import { useAudioCapture } from "./hooks/useAudioCapture"
import { useTranslatorSession } from "./hooks/useTranslatorSession"
import { DEFAULT_VAD_CONFIG } from "./providers/vad/types"
import type { SessionMode } from "./types"

const DEFAULT_TARGET_LANGUAGE = "es"

export default function App() {
  const [sourceLanguage, setSourceLanguage] = useState("auto")
  const [targetLanguage, setTargetLanguage] = useState(DEFAULT_TARGET_LANGUAGE)
  const [audioSource, setAudioSource] = useState("microphone")
  const [mode, setMode] = useState<SessionMode>("mock")
  const [isRunning, setIsRunning] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [showLatency, setShowLatency] = useState(import.meta.env.DEV)
  const [vadSilenceThresholdMs, setVadSilenceThresholdMs] = useState(
    DEFAULT_VAD_CONFIG.silenceThresholdMs,
  )
  const [vadSpeechThreshold, setVadSpeechThreshold] = useState(
    DEFAULT_VAD_CONFIG.speechProbThreshold,
  )

  const session = useTranslatorSession({ mode })
  const capture = useAudioCapture({
    onChunk: session.sendAudio,
    onVADEvent: session.sendVADEvent,
    vadConfig: {
      silenceThresholdMs: vadSilenceThresholdMs,
      speechProbThreshold: vadSpeechThreshold,
    },
  })

  const { setSpeaking } = session
  const { setVADConfig } = capture
  const speaking = capture.activityAvailable && capture.isSpeaking

  // The worklet's RMS check is only a fallback until the Silero VAD model is
  // ready; once ready, VAD lifecycle events drive the status instead.
  useEffect(() => {
    if (!capture.vadReady) setSpeaking(speaking)
  }, [capture.vadReady, speaking, setSpeaking])

  const handleStart = useCallback(async () => {
    const micOk = await capture.start()
    if (!micOk) return
    session.start({
      session_id: crypto.randomUUID(),
      source_language: sourceLanguage,
      target_language: targetLanguage,
      audio_source: audioSource,
      sample_rate: 16_000,
      encoding: "linear16",
    })
    setIsRunning(true)
  }, [capture, session, sourceLanguage, targetLanguage, audioSource])

  const handleStop = useCallback(() => {
    session.stop()
    capture.stop()
    setIsRunning(false)
  }, [capture, session])

  const handleModeChange = useCallback(
    (nextMode: SessionMode) => {
      if (nextMode !== mode) {
        session.stop()
        capture.stop()
        setIsRunning(false)
        setMode(nextMode)
      }
      setSettingsOpen(false)
    },
    [mode, session, capture],
  )

  const handleVADSilenceThresholdChange = useCallback(
    (value: number) => {
      setVadSilenceThresholdMs(value)
      setVADConfig({ silenceThresholdMs: value })
    },
    [setVADConfig],
  )

  const handleVADSpeechThresholdChange = useCallback(
    (value: number) => {
      setVadSpeechThreshold(value)
      setVADConfig({ speechProbThreshold: value })
    },
    [setVADConfig],
  )

  return (
    <main className="min-h-screen bg-slate-100 p-4 text-slate-900 sm:p-6">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <Header
          status={session.status}
          latency={session.latency}
          latencyVisible={import.meta.env.DEV && showLatency}
          vadStatus={capture.vadStatus}
          vadReady={capture.vadReady}
          vadError={capture.vadError}
          vadVisible={capture.isCapturing}
          onOpenSettings={() => setSettingsOpen(true)}
        />

        <ErrorBanner message={session.error ?? capture.error} onDismiss={session.dismissError} />

        <section className="flex flex-col gap-5 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <LanguageControls
            sourceValue={sourceLanguage}
            targetValue={targetLanguage}
            sourceOptions={SOURCE_LANGUAGES}
            targetOptions={LANGUAGES}
            onSourceChange={setSourceLanguage}
            onTargetChange={setTargetLanguage}
            disabled={isRunning}
          />
          <div className="border-t border-slate-100 pt-5">
            <AudioControls
              isRunning={isRunning}
              isCapturing={capture.isCapturing}
              audioSource={audioSource}
              audioSources={AUDIO_SOURCES}
              onAudioSourceChange={setAudioSource}
              onStart={() => void handleStart()}
              onStop={handleStop}
              disabled={mode === "live" && !navigator.mediaDevices?.getUserMedia}
            />
          </div>
        </section>

        <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <TranscriptPanel
            segments={session.transcriptSegments}
            partial={session.partialText}
            status={session.status}
          />
          <TranslationPanel
            latest={session.latestTranslation}
            history={session.translationSegments}
            targetLanguage={targetLanguage}
          />
        </section>

        {import.meta.env.DEV && (
          <DiagnosticsPanel
            sampleRate={capture.sampleRate}
            chunkSizeBytes={capture.chunkSizeBytes}
            chunksPerSecond={capture.chunksPerSecond}
            bytesSent={capture.bytesSent}
            bytesReceived={session.bytesReceived}
            connectionState={session.connectionState}
            vadStatus={capture.vadStatus}
            vadReady={capture.vadReady}
            vadError={capture.vadError}
            vadProbability={capture.vadProbability}
            vadSilenceThresholdMs={vadSilenceThresholdMs}
          />
        )}

        {mode === "mock" && (
          <p className="text-center text-xs text-slate-400">
            Demo mode — microphone audio is captured locally but not sent anywhere. Open
            settings and switch to Live WebSocket to stream audio to the backend.
          </p>
        )}
      </div>

      <SettingsModal
        open={settingsOpen}
        mode={mode}
        showLatency={showLatency}
        latencyToggleAvailable={import.meta.env.DEV}
        vadSilenceThresholdMs={vadSilenceThresholdMs}
        vadSpeechThreshold={vadSpeechThreshold}
        onModeChange={handleModeChange}
        onShowLatencyChange={setShowLatency}
        onVADSilenceThresholdChange={handleVADSilenceThresholdChange}
        onVADSpeechThresholdChange={handleVADSpeechThresholdChange}
        onClose={() => setSettingsOpen(false)}
      />
    </main>
  )
}
