import type { SessionStatus } from "../../types"

interface StatusMeta {
  label: string
  dot: string
  text: string
}

const STATUS_META: Record<SessionStatus, StatusMeta> = {
  idle: { label: "Idle", dot: "bg-slate-400", text: "text-slate-500" },
  connecting: { label: "Connecting", dot: "bg-amber-400 animate-pulse", text: "text-amber-600" },
  connected: { label: "Connected", dot: "bg-sky-500", text: "text-sky-600" },
  listening: { label: "Listening", dot: "bg-emerald-500 animate-pulse", text: "text-emerald-600" },
  speaking: { label: "Speaking", dot: "bg-emerald-500", text: "text-emerald-700" },
  silence: { label: "Silence detected", dot: "bg-slate-400", text: "text-slate-500" },
  translating: { label: "Translating", dot: "bg-violet-500 animate-pulse", text: "text-violet-600" },
  reconnecting: { label: "Reconnecting", dot: "bg-amber-400 animate-pulse", text: "text-amber-600" },
  error: { label: "Error", dot: "bg-rose-500 animate-pulse", text: "text-rose-600" },
  disconnected: { label: "Disconnected", dot: "bg-slate-400", text: "text-slate-500" },
}

export interface ConnectionStatusProps {
  status: SessionStatus
}

export function ConnectionStatus({ status }: ConnectionStatusProps) {
  const meta = STATUS_META[status]
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm shadow-sm"
    >
      <span className={`h-2.5 w-2.5 rounded-full ${meta.dot}`} aria-hidden="true" />
      <span className={`font-medium ${meta.text}`}>{meta.label}</span>
    </div>
  )
}
