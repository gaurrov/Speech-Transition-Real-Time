import type { LatencyReport } from "../../types"

export interface LatencyIndicatorProps {
  latency: LatencyReport | null
  visible: boolean
}

const LATENCY_KEYS = ["translation_ms", "asr_ms", "end_to_end_ms"] as const
type LatencyKey = (typeof LATENCY_KEYS)[number]

const LABELS: Record<LatencyKey, string> = {
  translation_ms: "Translation",
  asr_ms: "ASR",
  end_to_end_ms: "Latency",
}

export function LatencyIndicator({ latency, visible }: LatencyIndicatorProps) {
  if (!visible) return null
  const entry = (() => {
    if (!latency) return null
    for (const key of LATENCY_KEYS) {
      const value = latency[key]
      if (value !== null && value !== undefined) return { key, value }
    }
    return null
  })()
  return (
    <div
      title="Pipeline latency (dev mode)"
      className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 font-mono text-sm shadow-sm"
    >
      <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
        {entry === null ? "Latency" : LABELS[entry.key]}
      </span>
      <span className={entry === null ? "text-slate-400" : "text-slate-700"}>
        {entry === null ? "—" : `${Math.round(entry.value)} ms`}
      </span>
    </div>
  )
}
