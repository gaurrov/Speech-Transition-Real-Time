import { useEffect } from "react"
import type { ReactNode } from "react"
import type { AudioSourceKind } from "../../providers/audio/sources"
import type { SessionMode } from "../../types"
import { XIcon } from "../icons"

export interface SettingsModalProps {
  open: boolean
  mode: SessionMode
  showLatency: boolean
  latencyToggleAvailable: boolean
  vadSilenceThresholdMs: number
  vadSpeechThreshold: number
  audioSource: AudioSourceKind
  inElectron: boolean
  /** Settings are locked while a capture session is running. */
  disabled: boolean
  onAudioSourceChange: (kind: AudioSourceKind) => void
  onModeChange: (mode: SessionMode) => void
  onShowLatencyChange: (value: boolean) => void
  onVADSilenceThresholdChange: (value: number) => void
  onVADSpeechThresholdChange: (value: number) => void
  onClose: () => void
  /** Dev-only content (e.g. audio diagnostics) rendered below the settings. */
  children?: ReactNode
}

export function SettingsModal({
  open,
  mode,
  showLatency,
  latencyToggleAvailable,
  vadSilenceThresholdMs,
  vadSpeechThreshold,
  audioSource,
  inElectron,
  disabled,
  onAudioSourceChange,
  onModeChange,
  onShowLatencyChange,
  onVADSilenceThresholdChange,
  onVADSpeechThresholdChange,
  onClose,
  children,
}: SettingsModalProps) {
  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Settings"
    >
      <button
        type="button"
        className="absolute inset-0 bg-slate-900/40"
        onClick={onClose}
        aria-label="Close settings"
      />
      <div className="relative w-full max-w-md rounded-xl bg-white p-5 shadow-xl">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-900">Settings</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <XIcon className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4 flex flex-col gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
              Connection mode
            </span>
            <select
              value={mode}
              onChange={(event) => onModeChange(event.target.value as SessionMode)}
              className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none"
            >
              <option value="mock">Demo (no backend)</option>
              <option value="live">Live WebSocket</option>
            </select>
            <span className="text-xs text-slate-400">
              Demo mode captures your microphone locally without transmitting audio. Use
              Live WebSocket to stream to the backend.
            </span>
          </label>

          <fieldset className="flex flex-col gap-3 border-t border-slate-100 pt-4">
            <legend className="text-xs font-medium uppercase tracking-wide text-slate-500">
              Audio source
            </legend>

            <label className="flex flex-col gap-1">
              <select
                value={audioSource}
                disabled={disabled}
                onChange={(event) => onAudioSourceChange(event.target.value as AudioSourceKind)}
                className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none disabled:cursor-not-allowed disabled:bg-slate-100"
              >
                <option value="microphone">Microphone</option>
                <option value="system">System audio (meeting / browser)</option>
              </select>
              <span className="text-xs text-slate-400">
                Microphone uses your mic. System audio captures a meeting window or the whole
                screen so you can translate others' speech while you listen.
              </span>
            </label>

            {audioSource === "system" && (
              <div className="flex flex-col gap-2">
                {!inElectron ? (
                  <p
                    role="alert"
                    className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700"
                  >
                    System audio capture requires the Electron companion app. Keep using
                    Microphone in a plain browser tab.
                  </p>
                ) : (
                  <div className="flex flex-col gap-1">
                    <p className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                      Captures everything the computer is playing right now — including the
                      meeting app's audio. On Windows, Chromium no longer exposes
                      per-window audio, so this is the supported mechanism. Select
                      <span className="font-medium"> Microphone </span>
                      to capture only your own voice.
                    </p>
                    <p className="text-xs text-slate-400">
                      Tip: start the meeting/video first, then press Start. The captions
                      window never plays sound, so it cannot feed back into the capture.
                    </p>
                  </div>
                )}
              </div>
            )}
          </fieldset>

          {latencyToggleAvailable && (
            <label className="flex items-center justify-between gap-3">
              <span className="text-sm text-slate-700">Show latency indicator</span>
              <input
                type="checkbox"
                checked={showLatency}
                onChange={(event) => onShowLatencyChange(event.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
              />
            </label>
          )}

          <fieldset className="flex flex-col gap-3 border-t border-slate-100 pt-4">
            <legend className="text-xs font-medium uppercase tracking-wide text-slate-500">
              Voice activity detection
            </legend>

            <label className="flex flex-col gap-2">
              <span className="flex items-center justify-between text-sm text-slate-700">
                Utterance silence threshold
                <span className="font-mono text-xs text-slate-500">{vadSilenceThresholdMs} ms</span>
              </span>
              <input
                type="range"
                min={100}
                max={1500}
                step={50}
                value={vadSilenceThresholdMs}
                onChange={(event) => onVADSilenceThresholdChange(Number(event.target.value))}
                className="accent-indigo-600"
              />
              <span className="text-xs text-slate-400">
                Short pauses (like a 100 ms breath) keep the same utterance. Silence longer
                than this ends the utterance and triggers the next one.
              </span>
            </label>

            <label className="flex flex-col gap-2">
              <span className="flex items-center justify-between text-sm text-slate-700">
                Speech sensitivity
                <span className="font-mono text-xs text-slate-500">{vadSpeechThreshold.toFixed(2)}</span>
              </span>
              <input
                type="range"
                min={0.3}
                max={0.9}
                step={0.05}
                value={vadSpeechThreshold}
                onChange={(event) => onVADSpeechThresholdChange(Number(event.target.value))}
                className="accent-indigo-600"
              />
              <span className="text-xs text-slate-400">
                Lower values detect quieter speech but can be triggered by background noise.
              </span>
            </label>
          </fieldset>
        </div>

        {children}
      </div>
    </div>
  )
}
