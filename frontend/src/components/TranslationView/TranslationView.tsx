import { languageLabel } from "../../config/languages"
import type { TranslationSegment } from "../../types"

export interface TranslationViewProps {
  latest: TranslationSegment | null
  targetLanguage: string
  /** Larger, reading-first layout (used in compact mode and idle state). */
  prominent?: boolean
}

export function TranslationView({ latest, targetLanguage, prominent = false }: TranslationViewProps) {
  if (!latest) {
    return (
      <p className="text-sm text-slate-400">The translation will appear here.</p>
    )
  }

  return (
    <div className="flex h-full flex-col justify-center gap-1.5">
      <p
        className={`font-medium leading-snug text-slate-900 ${
          prominent ? "text-xl" : "text-base"
        } ${latest.is_final ? "" : "italic text-slate-600"}`}
      >
        {latest.translated_text}
      </p>
      <p className="text-[11px] text-slate-400">
        {latest.is_final ? "Translated" : "Translating…"} · → {languageLabel(targetLanguage)}
      </p>
    </div>
  )
}
