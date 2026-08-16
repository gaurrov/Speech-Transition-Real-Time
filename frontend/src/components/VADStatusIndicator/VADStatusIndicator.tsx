import type { VADStatus } from "../../providers/vad/types"

interface StatusMeta {
  label: string
  dot: string
  text: string
}

export interface VADStatusIndicatorProps {
  status: VADStatus
  ready: boolean
  error: string | null
  /** Render only while the microphone is being captured. */
  visible: boolean
}

export function VADStatusIndicator({
  status,
  ready,
  error,
  visible,
}: VADStatusIndicatorProps) {
  if (!visible) return null

  let meta: StatusMeta
  if (error) {
    meta = { label: "VAD error", dot: "bg-rose-500 animate-pulse", text: "text-rose-600" }
  } else if (!ready) {
    meta = { label: "VAD loading…", dot: "bg-amber-400 animate-pulse", text: "text-amber-600" }
  } else if (status === "speaking") {
    meta = { label: "Speaking", dot: "bg-emerald-500", text: "text-emerald-700" }
  } else if (status === "silence") {
    meta = { label: "Silence detected", dot: "border-slate-400", text: "text-slate-500" }
  } else {
    meta = { label: "Listening", dot: "bg-emerald-500", text: "text-emerald-600" }
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm shadow-sm"
    >
      <span
        className={`h-2.5 w-2.5 rounded-full ${status === "silence" && ready ? "border-2" : ""} ${meta.dot}`}
        aria-hidden="true"
      />
      <span className={`font-medium ${meta.text}`}>{meta.label}</span>
    </div>
  )
}
