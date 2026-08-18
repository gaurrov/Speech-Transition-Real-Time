import type { SessionStatus } from "../../types"
import { MicIcon, PlayIcon, StopIcon } from "../icons"
import { isActive, statusMeta } from "../status"

export interface ListeningControlsProps {
  status: SessionStatus
  isRunning: boolean
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
    <footer className="flex shrink-0 items-center gap-3 border-t border-slate-200 bg-white px-4 py-2">
      {/* Status indicator */}
      <div
        role="status"
        aria-live="polite"
        className="flex min-w-0 flex-1 items-center gap-2.5"
      >
        <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${active ? "bg-emerald-50" : "bg-slate-100"}`}>
          <MicIcon
            className={`h-3.5 w-3.5 ${active ? "text-emerald-600" : "text-slate-400"}`}
          />
        </div>
        <div className="flex min-w-0 flex-col">
          <span className={`text-[12px] font-medium ${active ? "text-slate-700" : "text-slate-500"}`}>
            {isRunning ? meta.label : "Stopped"}
          </span>
          {sourceLabel && isRunning && (
            <span className="truncate text-[10px] text-slate-400">
              {sourceLabel}
            </span>
          )}
        </div>
      </div>

      {/* Start / Stop button */}
      {isRunning ? (
        <button
          type="button"
          onClick={onStop}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-1.5 text-[12px] font-semibold text-white transition-colors hover:bg-slate-800"
        >
          <StopIcon className="h-3 w-3" />
          Stop
        </button>
      ) : (
        <button
          type="button"
          onClick={onStart}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-1.5 text-[12px] font-semibold text-white transition-colors hover:bg-indigo-700"
        >
          <PlayIcon className="h-3 w-3" />
          Start
        </button>
      )}
    </footer>
  )
}
