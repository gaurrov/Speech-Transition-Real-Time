import { useEffect } from "react"
import type { SessionMode } from "../../types"
import { XIcon } from "../icons"

export interface SettingsModalProps {
  open: boolean
  mode: SessionMode
  showLatency: boolean
  latencyToggleAvailable: boolean
  onModeChange: (mode: SessionMode) => void
  onShowLatencyChange: (value: boolean) => void
  onClose: () => void
}

export function SettingsModal({
  open,
  mode,
  showLatency,
  latencyToggleAvailable,
  onModeChange,
  onShowLatencyChange,
  onClose,
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
              <option value="mock">Mock demo (simulated stream)</option>
              <option value="live">Live WebSocket</option>
            </select>
            <span className="text-xs text-slate-400">
              Mock mode simulates the streaming pipeline without a backend.
            </span>
          </label>

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
        </div>
      </div>
    </div>
  )
}
