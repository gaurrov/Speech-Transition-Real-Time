import { useEffect, useRef } from "react"
import type { TranslationSegment } from "../../types"

export interface TranslationViewProps {
  latest: TranslationSegment | null
  targetLanguage: string
  translating?: boolean
  translationError?: string | null
  prominent?: boolean
  history?: TranslationSegment[]
}

export function TranslationView({
  latest,
  targetLanguage: _targetLanguage,
  translating = false,
  translationError = null,
  prominent = false,
  history,
}: TranslationViewProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [history, latest, translating])

  const hasHistory = history && history.length > 0
  const hasTranslation = latest != null

  if (!hasTranslation && !hasHistory && !translating && !translationError) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-slate-400">Translations will appear here</p>
      </div>
    )
  }

  const segments = hasHistory ? history! : hasTranslation ? [latest!] : []

  return (
    <div ref={scrollRef} className="flex h-full flex-col overflow-y-auto">
      <div className="flex flex-col gap-2.5 px-3 py-2.5">
        {segments.map((segment) => {
          const isLatest = segment.segment_id === latest?.segment_id
          return (
            <div
              key={segment.segment_id}
              className={`flex flex-col gap-1.5 rounded-md px-3 py-2 ${
                isLatest
                  ? "border-l-2 border-indigo-400 bg-slate-50/80"
                  : "border-l-2 border-transparent"
              }`}
            >
              {/* Source text — subdued */}
              <p className="text-[11px] leading-relaxed text-slate-400 break-words">
                {segment.source_text}
              </p>

              {/* Translated text — prominent */}
              <p
                className={`leading-snug break-words text-slate-900 ${
                  prominent ? "text-[15px] font-medium" : "text-[13px] font-medium"
                } ${!segment.is_final ? "italic text-slate-500" : ""}`}
              >
                {segment.translated_text}
              </p>
            </div>
          )
        })}

        {/* Pending translation indicator */}
        {translating && (
          <div className="flex items-center gap-2 px-3 py-1.5">
            <span className="inline-block animate-spin text-indigo-500 text-xs">&#x27F3;</span>
            <span className="text-[11px] font-medium text-indigo-500">Translating…</span>
          </div>
        )}

        {/* Translation error */}
        {translationError && (
          <div className="flex items-center gap-2 px-3 py-1.5">
            <span className="shrink-0 text-[11px] text-amber-500">●</span>
            <p className="text-[11px] text-amber-600">
              Translation unavailable — will retry next utterance
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
