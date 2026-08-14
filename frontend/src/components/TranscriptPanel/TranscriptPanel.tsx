import { useEffect, useRef } from "react"
import type { SessionStatus, TranscriptSegment } from "../../types"

export interface TranscriptPanelProps {
  segments: TranscriptSegment[]
  partial: string
  status: SessionStatus
}

const STATUS_CHIP: Partial<Record<SessionStatus, { label: string; className: string }>> = {
  speaking: { label: "Speaking", className: "bg-emerald-100 text-emerald-700" },
  silence: { label: "Silence", className: "bg-slate-100 text-slate-500" },
  listening: { label: "Listening", className: "bg-sky-100 text-sky-700" },
}

export function TranscriptPanel({ segments, partial, status }: TranscriptPanelProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [segments, partial])

  const chip = STATUS_CHIP[status]

  return (
    <section className="flex flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-700">Transcript</h2>
        {chip ? (
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${chip.className}`}
          >
            {chip.label}
          </span>
        ) : (
          <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
            Original
          </span>
        )}
      </header>
      <div ref={scrollRef} className="flex h-80 flex-col gap-3 overflow-y-auto px-4 py-3">
        {segments.length === 0 && !partial && (
          <p className="text-sm text-slate-400">
            Captions will appear here while you speak.
          </p>
        )}
        {segments.map((segment) => (
          <p
            key={segment.segment_id}
            className="text-[15px] leading-relaxed text-slate-800"
          >
            {segment.text}
            {segment.refined && (
              <span className="ml-2 rounded bg-indigo-50 px-1.5 py-0.5 align-middle text-[10px] font-medium uppercase tracking-wide text-indigo-500">
                refined
              </span>
            )}
          </p>
        ))}
        {partial && (
          <p className="flex items-start gap-2 text-[15px] leading-relaxed italic text-slate-500">
            <span className="mt-1.5 h-2 w-2 shrink-0 animate-pulse rounded-full bg-emerald-500" />
            {partial}
          </p>
        )}
      </div>
    </section>
  )
}
