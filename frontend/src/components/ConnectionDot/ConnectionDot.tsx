import type { SessionStatus } from "../../types"
import { statusMeta } from "../status"

export interface ConnectionDotProps {
  status: SessionStatus
  /** Show the text label next to the dot (defaults to true). */
  showLabel?: boolean
}

export function ConnectionDot({ status, showLabel = true }: ConnectionDotProps) {
  const meta = statusMeta(status)
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-1.5 rounded-full bg-slate-100 px-2 py-0.5"
      title={meta.label}
    >
      <span className={`h-2 w-2 rounded-full ${meta.dotClass}`} aria-hidden="true" />
      {showLabel && (
        <span className={`text-[11px] font-semibold ${meta.textClass}`}>{meta.label}</span>
      )}
    </div>
  )
}
