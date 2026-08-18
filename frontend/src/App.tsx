import { useCallback, useEffect, useRef, useState } from "react"
import { CompactHeader } from "./components/CompactHeader"
import { DiagnosticsPanel } from "./components/DiagnosticsPanel"
import { ErrorBanner } from "./components/ErrorBanner"
import { TranslationWarning } from "./components/TranslationWarning"
import { LanguageBar } from "./components/LanguageBar"
import { LatencyIndicator } from "./components/LatencyIndicator"
import { ListeningControls } from "./components/ListeningControls"
import { OverlayView } from "./components/OverlayView"
import { SettingsModal } from "./components/SettingsModal"
import { TranscriptView } from "./components/TranscriptView"
import { TranslationView } from "./components/TranslationView"
import { statusMeta } from "./components/status"
import { LANGUAGES, SOURCE_LANGUAGES, languageLabel } from "./config/languages"
import { loadPreferences, savePreferences } from "./config/preferences"
import { useAudioCapture } from "./hooks/useAudioCapture"
import { useBackendHealth } from "./hooks/useBackendHealth"
import { useTranslatorSession } from "./hooks/useTranslatorSession"
import { createAudioSource, type AudioSourceKind } from "./providers/audio/sources"
import { DEFAULT_VAD_CONFIG } from "./providers/vad/types"
import type { SessionMode, WindowMode } from "./types"

function shortCode(code: string): string {
  return code === "auto" ? "AUTO" : code.toUpperCase()
}

export default function App() {
  const prefsRef = useRef(loadPreferences())

  const [sourceLanguage, setSourceLanguage] = useState(prefsRef.current.sourceLanguage)
  const [targetLanguage, setTargetLanguage] = useState(prefsRef.current.targetLanguage)
  const [windowMode, setWindowMode] = useState<WindowMode>(prefsRef.current.windowMode)
  const [mode, setMode] = useState<SessionMode>(prefsRef.current.sessionMode)
  const [audioSource, setAudioSource] = useState<AudioSourceKind>(prefsRef.current.audioSource)
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

  const health = useBackendHealth()
  const session = useTranslatorSession({ mode, translationAvailable: health.translationAvailable })
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
      audioSource,
    })
  }, [sourceLanguage, targetLanguage, windowMode, mode, audioSource])

  // Keep the pin button in sync with the OS window state.
  useEffect(() => {
    if (!window.desktop) return
    void window.desktop.isAlwaysOnTop().then(setPinned)
    const unsubscribe = window.desktop.onAlwaysOnTopChanged(setPinned)
    return unsubscribe
  }, [])

  const translationWarning =
    health.checked && health.translationAvailable === false
      ? "Translation is currently unavailable — captions will still work, but nothing will be translated. This usually means the NLLB service isn't configured or reachable. See docs/translation.md."
      : null

  const handleStart = useCallback(async () => {
    health.recheck()
    const source = createAudioSource(audioSource)
    const ok = await capture.start(source)
    if (!ok) return
    session.start({
      session_id: crypto.randomUUID(),
      source_language: sourceLanguage,
      target_language: targetLanguage,
      audio_source: audioSource === "system" ? "system" : "microphone",
      sample_rate: 16_000,
      encoding: "linear16",
    })
    setIsRunning(true)
  }, [capture, session, sourceLanguage, targetLanguage, audioSource, health.recheck])

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
    setWindowMode((current) => {
      if (current === "expanded") return "compact"
      if (current === "compact") return "overlay"
      return "expanded"
    })
  }, [])

  const handleTogglePinned = useCallback(async () => {
    if (!window.desktop) return
    setPinned(await window.desktop.toggleAlwaysOnTop())
  }, [])

  const statusChip = statusMeta(session.status)
  const error = session.error ?? capture.error

  if (windowMode === "overlay") {
    return (
      <main className="flex h-full flex-col overflow-hidden">
        <OverlayView
          status={session.status}
          isRunning={isRunning}
          latestTranslation={session.latestTranslation}
          translationError={session.translationError}
          transcriptSegments={session.transcriptSegments}
          partialText={session.partialText}
          sourceLanguage={sourceLanguage}
          targetLanguage={targetLanguage}
          onStart={() => void handleStart()}
          onStop={handleStop}
          onExpand={() => setWindowMode("expanded")}
          onOpenSettings={() => setSettingsOpen(true)}
        />

        <SettingsModal
          open={settingsOpen}
          mode={mode}
          showLatency={showLatency}
          latencyToggleAvailable={import.meta.env.DEV}
          vadSilenceThresholdMs={vadSilenceThresholdMs}
          vadSpeechThreshold={vadSpeechThreshold}
          audioSource={audioSource}
          inElectron={inElectron}
          disabled={isRunning}
          onAudioSourceChange={setAudioSource}
          onModeChange={handleModeChange}
          onShowLatencyChange={setShowLatency}
          onVADSilenceThresholdChange={handleVADSilenceThresholdChange}
          onVADSpeechThresholdChange={handleVADSpeechThresholdChange}
          onClose={() => setSettingsOpen(false)}
        />
      </main>
    )
  }

  return (
    <main className={`flex h-full items-stretch justify-center overflow-hidden text-slate-900 ${inElectron ? "bg-white" : "bg-slate-100 p-2"}`}>
      <div className={`flex h-full w-full max-w-[480px] flex-col overflow-hidden bg-white ${inElectron ? "" : "rounded-xl border border-slate-200 shadow-lg"}`}>
        {/* Header — shrink-to-fit */}
        <CompactHeader
          status={session.status}
          windowMode={windowMode}
          pinned={pinned}
          inElectron={inElectron}
          sourceLabel={shortCode(sourceLanguage)}
          targetLabel={languageLabel(targetLanguage)}
          onToggleWindowMode={handleToggleWindowMode}
          onOpenSettings={() => setSettingsOpen(true)}
          onTogglePinned={() => void handleTogglePinned()}
          onMinimize={() => window.desktop?.minimize()}
          onClose={() => window.desktop?.close()}
        />

        <TranslationWarning message={translationWarning} />

        <ErrorBanner
          message={error}
          onDismiss={() => session.dismissError()}
        />

        {/* Content — flex-1, fills available vertical space */}
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

            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              {/* Transcript — compact, max 25% height */}
              <div className="flex shrink-0 flex-col border-b border-slate-100" style={{ maxHeight: "25%" }}>
                <div className="flex items-center justify-between px-3 py-1">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                    Speech
                  </span>
                  <span
                    className={`text-[10px] font-medium ${statusChip.textClass}`}
                  >
                    {statusChip.label}
                  </span>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-1.5">
                  <TranscriptView
                    segments={session.transcriptSegments}
                    partial={session.partialText}
                    status={session.status}
                  />
                </div>
              </div>

              {/* Translation — primary, fills remaining space */}
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                <TranslationView
                  latest={session.latestTranslation}
                  targetLanguage={targetLanguage}
                  translating={session.status === "translating"}
                  translationError={session.translationError}
                  history={session.translationSegments}
                />
              </div>
            </div>
          </>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <TranslationView
              latest={session.latestTranslation}
              targetLanguage={targetLanguage}
              translating={session.status === "translating"}
              translationError={session.translationError}
              prominent
            />
          </div>
        )}

        {/* Footer — shrink-to-fit, pinned to bottom */}
        <ListeningControls
          status={session.status}
          isRunning={isRunning}
          sourceLabel={audioSource === "system" ? "System audio" : "Microphone"}
          onStart={() => void handleStart()}
          onStop={handleStop}
        />
      </div>

      <SettingsModal
        open={settingsOpen}
        mode={mode}
        showLatency={showLatency}
        latencyToggleAvailable={import.meta.env.DEV}
        vadSilenceThresholdMs={vadSilenceThresholdMs}
        vadSpeechThreshold={vadSpeechThreshold}
        audioSource={audioSource}
        inElectron={inElectron}
        disabled={isRunning}
        onAudioSourceChange={setAudioSource}
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
