import type { SessionStatus } from "../types"

export interface StatusMeta {
  label: string
  dotClass: string
  textClass: string
}

const META: Record<SessionStatus, StatusMeta> = {
  idle: { label: "Idle", dotClass: "bg-slate-400", textClass: "text-slate-500" },
  connecting: {
    label: "Connecting",
    dotClass: "bg-amber-400 animate-pulse",
    textClass: "text-amber-600",
  },
  connected: { label: "Connected", dotClass: "bg-sky-500", textClass: "text-sky-600" },
  listening: {
    label: "Listening",
    dotClass: "bg-emerald-500 animate-pulse",
    textClass: "text-emerald-600",
  },
  speaking: { label: "Speaking", dotClass: "bg-emerald-500", textClass: "text-emerald-700" },
  silence: { label: "Listening", dotClass: "bg-emerald-500 animate-pulse", textClass: "text-emerald-600" },
  translating: {
    label: "Translating",
    dotClass: "bg-violet-500 animate-pulse",
    textClass: "text-violet-600",
  },
  reconnecting: {
    label: "Reconnecting",
    dotClass: "bg-amber-400 animate-pulse",
    textClass: "text-amber-600",
  },
  error: { label: "Error", dotClass: "bg-rose-500 animate-pulse", textClass: "text-rose-600" },
  disconnected: { label: "Offline", dotClass: "bg-slate-400", textClass: "text-slate-500" },
}

export function statusMeta(status: SessionStatus): StatusMeta {
  return META[status]
}

/** True when the session is actively capturing/translating. */
export function isActive(status: SessionStatus): boolean {
  return (
    status === "listening" ||
    status === "speaking" ||
    status === "silence" ||
    status === "translating"
  )
}
