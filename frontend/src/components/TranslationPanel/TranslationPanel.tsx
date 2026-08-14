import { useEffect, useRef } from "react"
import { languageLabel } from "../../config/languages"
import type { TranslationSegment } from "../../types"

export interface TranslationPanelProps {
  latest: TranslationSegment | null
  history: TranslationSegment[]
  targetLanguage: string
}

export function TranslationPanel({ latest, history, targetLanguage }: TranslationPanelProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
  }, [latest])

  const previous = history.length > 1 ? history.slice(0, -1).reverse() : []

  return (
    <section className="flex flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-700">Translation</h2>
        <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-600">
          → {languageLabel(targetLanguage)}
        </span>
      </header>
      <div className="flex h-80 flex-col px-4 py-3">
        {latest ? (
          <div className="flex flex-col gap-1.5 rounded-lg border border-indigo-100 bg-indigo-50/50 px-4 py-3">
            <span className="text-[11px] font-medium uppercase tracking-wide text-indigo-500">
              {latest.is_final ? "Latest translation" : "Latest translation (draft)"}
            </span>
            <p
              className={`text-lg leading-relaxed text-slate-900 ${
                latest.is_final ? "" : "italic text-slate-600"
              }`}
            >
              {latest.translated_text}
            </p>
          </div>
        ) : (
          <p className="text-sm text-slate-400">The translated utterance will appear here.</p>
        )}
        {previous.length > 0 && (
          <div
            ref={scrollRef}
            className="mt-3 max-h-24 space-y-1.5 overflow-y-auto border-t border-slate-100 pt-2"
          >
            {previous.map((segment) => (
              <p key={segment.segment_id} className="text-xs leading-relaxed text-slate-500">
                {segment.translated_text}
              </p>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
