import type { SessionStatus } from "../../types"
import { MicIcon, PlayIcon, StopIcon } from "../icons"
import { isActive, statusMeta } from "../status"

export interface ListeningControlsProps {
  status: SessionStatus
  isRunning: boolean
  /** Active capture source label (e.g. "Microphone" or the window name). */
  sourceLabel?: string
  onStart: () => void
  onStop: () => void
}

export function ListeningControls({
  status,
  isRunning,
  sourceLabel,
  onStart,
  onStop,
}: ListeningControlsProps) {
  const meta = statusMeta(status)
  const active = isRunning && isActive(status)

  return (
    <footer className="flex shrink-0 items-center justify-between gap-2 border-t border-slate-200 bg-white px-3 py-2">
      <div
        role="status"
        aria-live="polite"
        className="flex min-w-0 items-center gap-2 rounded-full bg-slate-100 px-2.5 py-1"
      >
        <MicIcon
          className={`h-3.5 w-3.5 shrink-0 ${active ? "text-emerald-600" : "text-slate-400"}`}
        />
        <span className="flex items-center gap-1.5 truncate text-xs font-semibold text-slate-600">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${active ? `${meta.dotClass}` : "bg-slate-400"}`}
            aria-hidden="true"
          />
          {isRunning ? meta.label : "Off"}
        </span>
        {sourceLabel && isRunning && (
          <span className="truncate rounded-full bg-indigo-50 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-600">
            {sourceLabel}
          </span>
        )}
      </div>

      {isRunning ? (
        <button
          type="button"
          onClick={onStop}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-rose-600 px-4 py-1.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-rose-700"
        >
          <StopIcon className="h-3.5 w-3.5" />
          Stop
        </button>
      ) : (
        <button
          type="button"
          onClick={onStart}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-emerald-700"
        >
          <PlayIcon className="h-3.5 w-3.5" />
          Start
        </button>
      )}
    </footer>
  )
}
