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
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-100">
          <svg className="h-5 w-5 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
          </svg>
        </div>
        <p className="text-center text-[13px] text-slate-400">
          Translations will appear here
        </p>
      </div>
    )
  }

  const segments = hasHistory ? history! : hasTranslation ? [latest!] : []

  return (
    <div ref={scrollRef} className="flex h-full flex-col overflow-y-auto">
      <div className="flex flex-col gap-0.5 py-2">
        {segments.map((segment, index) => {
          const isLatest = segment.segment_id === latest?.segment_id
          const isFirst = index === 0
          return (
            <div
              key={segment.segment_id}
              className={`flex flex-col gap-1 px-4 py-2.5 ${
                isLatest
                  ? "bg-indigo-50/60"
                  : ""
              } ${!isFirst ? "border-t border-slate-100" : ""}`}
            >
              {/* Source text */}
              <p className="text-[11px] leading-relaxed text-slate-400 break-words">
                {segment.source_text}
              </p>

              {/* Translated text */}
              <p
                className={`leading-snug break-words font-medium ${
                  prominent ? "text-[15px]" : "text-[14px]"
                } ${!segment.is_final ? "italic text-slate-400" : "text-slate-900"}`}
              >
                {segment.translated_text}
              </p>
            </div>
          )
        })}

        {/* Pending translation indicator */}
        {translating && (
          <div className="flex items-center gap-2.5 border-t border-slate-100 px-4 py-3">
            <div className="flex gap-1">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-400" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-400" style={{ animationDelay: "150ms" }} />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-400" style={{ animationDelay: "300ms" }} />
            </div>
            <span className="text-[12px] font-medium text-indigo-500">Translating</span>
          </div>
        )}

        {/* Translation error */}
        {translationError && (
          <div className="flex items-center gap-2 border-t border-slate-100 px-4 py-2.5">
            <div className="h-1.5 w-1.5 rounded-full bg-amber-400" />
            <p className="text-[11px] text-slate-500">
              Translation unavailable — will retry next utterance
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
