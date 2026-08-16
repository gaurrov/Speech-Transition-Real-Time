import { useCallback, useEffect, useRef, useState } from "react"
import { CompactHeader } from "./components/CompactHeader"
import { CompactPanel } from "./components/CompactPanel"
import { DiagnosticsPanel } from "./components/DiagnosticsPanel"
import { ErrorBanner } from "./components/ErrorBanner"
import { LanguageBar } from "./components/LanguageBar"
import { LatencyIndicator } from "./components/LatencyIndicator"
import { ListeningControls } from "./components/ListeningControls"
import { SettingsModal } from "./components/SettingsModal"
import { TranscriptView } from "./components/TranscriptView"
import { TranslationView } from "./components/TranslationView"
import { statusMeta } from "./components/status"
import { LANGUAGES, SOURCE_LANGUAGES } from "./config/languages"
import { loadPreferences, savePreferences } from "./config/preferences"
import { useAudioCapture } from "./hooks/useAudioCapture"
import { useTranslatorSession } from "./hooks/useTranslatorSession"
import { DEFAULT_VAD_CONFIG } from "./providers/vad/types"
import type { SessionMode, WindowMode } from "./types"

const AUDIO_SOURCE = "microphone"

function shortCode(code: string): string {
  return code === "auto" ? "AUTO" : code.toUpperCase()
}

export default function App() {
  const prefsRef = useRef(loadPreferences())

  const [sourceLanguage, setSourceLanguage] = useState(prefsRef.current.sourceLanguage)
  const [targetLanguage, setTargetLanguage] = useState(prefsRef.current.targetLanguage)
  const [windowMode, setWindowMode] = useState<WindowMode>(prefsRef.current.windowMode)
  const [mode, setMode] = useState<SessionMode>(prefsRef.current.sessionMode)
  const [isRunning, setIsRunning] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [showLatency, setShowLatency] = useState(import.meta.env.DEV)
  const [pinned, setPinned] = useState(true)
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

  const inElectron = window.desktop?.isElectron === true

  useEffect(() => {
    if (!capture.vadReady) setSpeaking(speaking)
  }, [capture.vadReady, speaking, setSpeaking])

  // Persist user choices so the companion window reopens in the same state.
  useEffect(() => {
    savePreferences({
      sourceLanguage,
      targetLanguage,
      windowMode,
      sessionMode: mode,
    })
  }, [sourceLanguage, targetLanguage, windowMode, mode])

  // Keep the pin button in sync with the OS window state.
  useEffect(() => {
    if (!window.desktop) return
    void window.desktop.isAlwaysOnTop().then(setPinned)
    const unsubscribe = window.desktop.onAlwaysOnTopChanged(setPinned)
    return unsubscribe
  }, [])

  const handleStart = useCallback(async () => {
    const micOk = await capture.start()
    if (!micOk) return
    session.start({
      session_id: crypto.randomUUID(),
      source_language: sourceLanguage,
      target_language: targetLanguage,
      audio_source: AUDIO_SOURCE,
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

  const handleToggleWindowMode = useCallback(() => {
    setWindowMode((current) => (current === "expanded" ? "compact" : "expanded"))
  }, [])

  const handleTogglePinned = useCallback(async () => {
    if (!window.desktop) return
    setPinned(await window.desktop.toggleAlwaysOnTop())
  }, [])

  const statusChip = statusMeta(session.status)
  const error = session.error ?? capture.error

  return (
    <main className="flex h-screen flex-col bg-slate-100 text-slate-900">
      <CompactHeader
        status={session.status}
        windowMode={windowMode}
        pinned={pinned}
        inElectron={inElectron}
        sourceLabel={shortCode(sourceLanguage)}
        targetLabel={shortCode(targetLanguage)}
        onToggleWindowMode={handleToggleWindowMode}
        onOpenSettings={() => setSettingsOpen(true)}
        onTogglePinned={() => void handleTogglePinned()}
        onMinimize={() => window.desktop?.minimize()}
        onClose={() => window.desktop?.close()}
      />

      <ErrorBanner
        message={error}
        onDismiss={() => session.dismissError()}
      />

      {windowMode === "expanded" ? (
        <>
          <LanguageBar
            sourceValue={sourceLanguage}
            targetValue={targetLanguage}
            sourceOptions={SOURCE_LANGUAGES}
            targetOptions={LANGUAGES}
            onSourceChange={setSourceLanguage}
            onTargetChange={setTargetLanguage}
            disabled={isRunning}
          />

          <div className="flex min-h-0 flex-1 flex-col gap-2 px-3 pb-2">
            <CompactPanel
              title="LIVE SPEECH"
              right={
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${statusChip.textClass} bg-slate-100`}
                >
                  {statusChip.label}
                </span>
              }
            >
              <TranscriptView
                segments={session.transcriptSegments}
                partial={session.partialText}
                status={session.status}
              />
            </CompactPanel>

            <CompactPanel title="TRANSLATION" accent>
              <TranslationView
                latest={session.latestTranslation}
                targetLanguage={targetLanguage}
                history={session.translationSegments}
              />
            </CompactPanel>
          </div>
        </>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col justify-center px-4 py-3">
          <TranslationView
            latest={session.latestTranslation}
            targetLanguage={targetLanguage}
            prominent
          />
        </div>
      )}

      <ListeningControls
        status={session.status}
        isRunning={isRunning}
        onStart={() => void handleStart()}
        onStop={handleStop}
      />

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
      >
        {import.meta.env.DEV && (
          <div className="flex flex-col gap-3 border-t border-slate-100 pt-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Pipeline latency
              </span>
              <LatencyIndicator
                latency={session.latency}
                visible={showLatency}
              />
            </div>
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
              latency={session.latency}
              latencyHistory={session.latencyHistory}
            />
          </div>
        )}
      </SettingsModal>
    </main>
  )
}
