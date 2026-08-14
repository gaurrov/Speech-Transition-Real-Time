import type { LatencyReport } from "../../types"

export interface LatencyIndicatorProps {
  latency: LatencyReport | null
  visible: boolean
}

export function LatencyIndicator({ latency, visible }: LatencyIndicatorProps) {
  if (!visible) return null
  const ms = latency?.end_to_end_ms ?? null
  return (
    <div
      title="End-to-end latency (dev mode)"
      className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 font-mono text-sm shadow-sm"
    >
      <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
        Latency
      </span>
      <span className={ms === null ? "text-slate-400" : "text-slate-700"}>
        {ms === null ? "—" : `${Math.round(ms)} ms`}
      </span>
    </div>
  )
}
