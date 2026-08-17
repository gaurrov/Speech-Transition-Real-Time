import { useEffect, useRef } from "react"
import { languageLabel } from "../../config/languages"
import type { TranslationSegment } from "../../types"

export interface TranslationViewProps {
  latest: TranslationSegment | null
  targetLanguage: string
  /** True while the backend is processing a pending_translation event. */
  translating?: boolean
  /** Non-null when a translation error occurred (cleared on next pending). */
  translationError?: string | null
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
  translating = false,
  translationError = null,
  prominent = false,
  history,
}: TranslationViewProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [history])

  const hasHistory = history && history.length > 0
  const hasTranslation = latest != null

  if (!hasTranslation && !hasHistory && !translating) {
    return (
      <p className="text-sm text-slate-400">The translation will appear here.</p>
    )
  }

  if (!hasHistory) {
    return (
      <div className="flex h-full flex-col justify-center gap-1.5">
        {translating && !hasTranslation ? (
          <p
            className={`font-medium leading-snug ${
              prominent ? "text-xl" : "text-base"
            } italic text-slate-500`}
          >
            <span className="animate-pulse">Translating…</span>
          </p>
        ) : hasTranslation ? (
          <p
            className={`font-medium leading-snug text-slate-900 ${
              prominent ? "text-xl" : "text-base"
            } ${latest!.is_final ? "" : "italic text-slate-600"}`}
          >
            {latest!.translated_text}
          </p>
        ) : null}
        {translating && !hasTranslation ? (
          <p className="text-[11px] text-slate-400">
            Translating… · → {languageLabel(targetLanguage)}
          </p>
        ) : hasTranslation ? (
          <p className="text-[11px] text-slate-400">
            {latest!.is_final ? "Translated" : "Translating…"} · →{" "}
            {languageLabel(targetLanguage)}
          </p>
        ) : null}
        {translating && hasTranslation && (
          <p className="text-[11px] italic text-slate-400">
            <span className="animate-pulse">⟳</span> Translating next…
          </p>
        )}
        {translationError && (
          <p className="text-[11px] text-amber-600">
            {translationError}
          </p>
        )}
      </div>
    )
  }

  return (
    <div ref={scrollRef} className="flex h-full max-h-full flex-col gap-2 overflow-y-auto">
      {history!.map((segment) => {
        const isLatest = segment.segment_id === latest?.segment_id
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
              } ${!segment.is_final ? "italic text-slate-600" : ""}`}
            >
              {segment.translated_text}
            </p>
            <p className="text-[11px] text-slate-400">{segment.source_text}</p>
            {isLatest && (
              <p className="text-[11px] text-slate-400">
                {segment.is_final ? "Translated" : "Translating…"} · →{" "}
                {languageLabel(targetLanguage)}
              </p>
            )}
          </div>
        )
      })}
      {translating && (
        <div className="rounded-md px-2.5 py-1.5">
          <p className="text-sm italic text-slate-500">
            <span className="animate-pulse">Translating…</span>
          </p>
        </div>
      )}
      {translationError && (
        <div className="rounded-md px-2.5 py-1.5">
          <p className="text-[11px] text-amber-600">{translationError}</p>
        </div>
      )}
    </div>
  )
}
