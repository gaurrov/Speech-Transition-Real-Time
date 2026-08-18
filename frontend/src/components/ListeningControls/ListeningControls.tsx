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
    <footer className="flex shrink-0 items-center gap-2 border-t border-slate-200/80 bg-slate-50/50 px-3 py-1.5">
      {/* Status indicator */}
      <div
        role="status"
        aria-live="polite"
        className="flex min-w-0 flex-1 items-center gap-2"
      >
        <MicIcon
          className={`h-3.5 w-3.5 shrink-0 ${active ? "text-emerald-500" : "text-slate-300"}`}
        />
        <span className="flex items-center gap-1.5 truncate text-[11px] font-medium text-slate-500">
          <span
            className={`h-1.5 w-1.5 shrink-0 rounded-full ${active ? meta.dotClass : "bg-slate-300"}`}
            aria-hidden="true"
          />
          {isRunning ? meta.label : "Stopped"}
        </span>
        {sourceLabel && isRunning && (
          <span className="hidden truncate text-[10px] text-slate-400 sm:block">
            {sourceLabel}
          </span>
        )}
      </div>

      {/* Start / Stop button */}
      {isRunning ? (
        <button
          type="button"
          onClick={onStop}
          className="flex shrink-0 items-center gap-1.5 rounded-md bg-rose-500 px-3 py-1 text-[11px] font-semibold text-white transition-colors hover:bg-rose-600"
        >
          <StopIcon className="h-2.5 w-2.5" />
          Stop
        </button>
      ) : (
        <button
          type="button"
          onClick={onStart}
          className="flex shrink-0 items-center gap-1.5 rounded-md bg-emerald-500 px-3 py-1 text-[11px] font-semibold text-white transition-colors hover:bg-emerald-600"
        >
          <PlayIcon className="h-2.5 w-2.5" />
          Start
        </button>
      )}
    </footer>
  )
}
