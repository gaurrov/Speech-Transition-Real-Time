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

  const active =
    status === "listening" || status === "speaking" || status === "silence" || status === "translating"

  if (segments.length === 0 && !partial) {
    return (
      <p className="text-[12px] text-slate-400">
        {active ? "Listening for speech..." : "Start to see captions here"}
      </p>
    )
  }

  return (
    <div ref={scrollRef} className="flex h-full max-h-full flex-col gap-0.5 overflow-y-auto">
      {segments.map((segment) => (
        <p key={segment.segment_id} className="text-[12px] leading-relaxed text-slate-600 break-words">
          {segment.text}
        </p>
      ))}
      {partial && (
        <p className="flex items-start gap-1.5 text-[12px] leading-relaxed text-slate-400 break-words">
          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-emerald-400" />
          {partial}
        </p>
      )}
    </div>
  )
}
