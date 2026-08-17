import { useEffect, useRef } from "react"
import { languageLabel } from "../../config/languages"
import type { TranslationSegment } from "../../types"

export interface TranslationViewProps {
  latest: TranslationSegment | null
  targetLanguage: string
  /** Larger, reading-first layout (used in compact mode and idle state). */
  prominent?: boolean
  /**
   * When provided, renders the full per-utterance translation history (used
   * in expanded mode) instead of just the latest result.
   */
  history?: TranslationSegment[]
}

export function TranslationView({
  latest,
  targetLanguage,
  prominent = false,
  history,
}: TranslationViewProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [history])

  if (!latest && (!history || history.length === 0)) {
    return (
      <p className="text-sm text-slate-400">The translation will appear here.</p>
    )
  }

  const isPending = latest?.provider === "pending"

  if (!history || history.length === 0) {
    return (
      <div className="flex h-full flex-col justify-center gap-1.5">
        {isPending ? (
          <p
            className={`font-medium leading-snug text-slate-900 ${
              prominent ? "text-xl" : "text-base"
            } italic text-slate-500`}
          >
            <span className="animate-pulse">Translating…</span>
          </p>
        ) : (
          <p
            className={`font-medium leading-snug text-slate-900 ${
              prominent ? "text-xl" : "text-base"
            } ${latest?.is_final ? "" : "italic text-slate-600"}`}
          >
            {latest?.translated_text}
          </p>
        )}
        <p className="text-[11px] text-slate-400">
          {isPending
            ? `Translating… · → ${languageLabel(targetLanguage)}`
            : `${latest?.is_final ? "Translated" : "Translating…"} · → ${languageLabel(targetLanguage)}`}
        </p>
      </div>
    )
  }

  return (
    <div ref={scrollRef} className="flex h-full max-h-full flex-col gap-2 overflow-y-auto">
      {history.map((segment) => {
        const isLatest = segment.segment_id === latest?.segment_id
        const segPending = segment.provider === "pending"
        return (
          <div
            key={segment.segment_id}
            className={`rounded-md px-2.5 py-1.5 ${
              isLatest ? "bg-indigo-50/70 ring-1 ring-indigo-100" : ""
            }`}
          >
            <p
              className={`font-medium leading-snug text-slate-900 ${
                isLatest ? "" : "text-sm"
              } ${segPending || !segment.is_final ? "italic text-slate-600" : ""}`}
            >
              {segPending ? (
                <span className="animate-pulse">Translating…</span>
              ) : (
                segment.translated_text
              )}
            </p>
            <p className="text-[11px] text-slate-400">{segment.source_text}</p>
            {isLatest && (
              <p className="text-[11px] text-slate-400">
                {segPending
                  ? `Translating… · → ${languageLabel(targetLanguage)}`
                  : `${segment.is_final ? "Translated" : "Translating…"} · → ${languageLabel(targetLanguage)}`}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}
