import { useCallback, useState } from "react"
import { AudioControls } from "./components/AudioControls"
import { ErrorBanner } from "./components/ErrorBanner"
import { Header } from "./components/Header"
import { LanguageControls } from "./components/LanguageControls"
import { SettingsModal } from "./components/SettingsModal"
import { TranscriptPanel } from "./components/TranscriptPanel"
import { TranslationPanel } from "./components/TranslationPanel"
import { AUDIO_SOURCES } from "./config/audioSources"
import { LANGUAGES, SOURCE_LANGUAGES, languageLabel } from "./config/languages"
import { useAudioCapture } from "./hooks/useAudioCapture"
import { useTranslatorSession } from "./hooks/useTranslatorSession"
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

  const session = useTranslatorSession({ mode })
  const capture = useAudioCapture({ simulate: mode === "mock" })

  const handleStart = useCallback(async () => {
    const micOk = await capture.start()
    if (!micOk) return
    session.start({
      source_language: sourceLanguage,
      target_language: targetLanguage,
      sample_rate: 16_000,
      encoding: "linear16",
    })
    setIsRunning(true)
  }, [capture, session, sourceLanguage, targetLanguage])

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

  return (
    <main className="min-h-screen bg-slate-100 p-4 text-slate-900 sm:p-6">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <Header
          status={session.status}
          latency={session.latency}
          latencyVisible={import.meta.env.DEV && showLatency}
          onOpenSettings={() => setSettingsOpen(true)}
        />

        <ErrorBanner message={session.error} onDismiss={session.dismissError} />

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

        {mode === "mock" && (
          <p className="text-center text-xs text-slate-400">
            Demo mode — {languageLabel(targetLanguage)} is simulated. Open settings to
            connect a live backend.
          </p>
        )}
      </div>

      <SettingsModal
        open={settingsOpen}
        mode={mode}
        showLatency={showLatency}
        latencyToggleAvailable={import.meta.env.DEV}
        onModeChange={handleModeChange}
        onShowLatencyChange={setShowLatency}
        onClose={() => setSettingsOpen(false)}
      />
    </main>
  )
}
