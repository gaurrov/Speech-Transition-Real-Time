import { useEffect, useRef } from "react"
import type { SessionStatus, TranscriptSegment } from "../../types"

export interface TranscriptViewProps {
  segments: TranscriptSegment[]
  partial: string
  status: SessionStatus
}

export function TranscriptView({ segments, partial, status }: TranscriptViewProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [segments, partial])

  const isActive =
    status === "listening" || status === "speaking" || status === "silence" || status === "translating"

  if (segments.length === 0 && !partial) {
    return (
      <p className="text-sm text-slate-400">
        {isActive ? "Listening for speech…" : "Captions will appear here while you speak."}
      </p>
    )
  }

  return (
    <div ref={scrollRef} className="flex h-full max-h-full flex-col gap-2 overflow-y-auto">
      {segments.map((segment) => (
        <p key={segment.segment_id} className="text-sm leading-relaxed text-slate-800">
          {segment.text}
          {segment.refined && (
            <span className="ml-2 rounded bg-indigo-50 px-1.5 py-0.5 align-middle text-[10px] font-medium uppercase tracking-wide text-indigo-500">
              refined
            </span>
          )}
        </p>
      ))}
      {partial && (
        <p className="flex items-start gap-2 text-sm leading-relaxed italic text-slate-500">
          <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
          {partial}
        </p>
      )}
    </div>
  )
}
