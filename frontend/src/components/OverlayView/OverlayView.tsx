import { useEffect, useRef } from "react"
import { languageLabel } from "../../config/languages"
import type { SessionStatus, TranslationSegment, TranscriptSegment } from "../../types"
import { GearIcon, GlobeIcon, ExpandIcon, MicIcon, PlayIcon, StopIcon } from "../icons"
import { statusMeta, isActive } from "../status"

export interface OverlayViewProps {
  status: SessionStatus
  isRunning: boolean
  latestTranslation: TranslationSegment | null
  translationError: string | null
  transcriptSegments: TranscriptSegment[]
  partialText: string
  sourceLanguage: string
  targetLanguage: string
  onStart: () => void
  onStop: () => void
  onExpand: () => void
  onOpenSettings: () => void
}

export function OverlayView({
  status,
  isRunning,
  latestTranslation,
  translationError,
  transcriptSegments,
  partialText,
  sourceLanguage,
  targetLanguage,
  onStart,
  onStop,
  onExpand,
  onOpenSettings,
}: OverlayViewProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const meta = statusMeta(status)
  const active = isRunning && isActive(status)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [latestTranslation, partialText])

  const lastTranscript = transcriptSegments.length > 0
    ? transcriptSegments[transcriptSegments.length - 1]
    : null

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-white">
      {/* Minimal header bar */}
      <header className="app-drag flex shrink-0 items-center gap-1.5 border-b border-slate-100 px-2.5 py-1.5">
        <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-indigo-600 text-white">
          <GlobeIcon className="h-3 w-3" />
        </div>
        <span className="flex-1 truncate text-[11px] font-semibold text-slate-600">
          {sourceLanguage.toUpperCase()} → {languageLabel(targetLanguage)}
        </span>
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${active ? meta.dotClass : "bg-slate-300"}`}
          aria-hidden="true"
        />
        <button
          type="button"
          onClick={onOpenSettings}
          className="app-no-drag flex h-5 w-5 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          title="Settings"
        >
          <GearIcon className="h-3 w-3" />
        </button>
        <button
          type="button"
          onClick={onExpand}
          className="app-no-drag flex h-5 w-5 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          title="Expand"
        >
          <ExpandIcon className="h-3 w-3" />
        </button>
      </header>

      {/* Content area — scrollable, shows translation + source */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {latestTranslation ? (
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-medium leading-snug text-slate-900 break-words">
              {latestTranslation.translated_text}
            </p>
            <div className="border-t border-slate-100" />
            <p className="text-[11px] leading-snug text-slate-400 break-words">
              {latestTranslation.source_text}
            </p>
          </div>
        ) : partialText ? (
          <p className="text-sm italic leading-snug text-slate-500 break-words">
            {partialText}
          </p>
        ) : lastTranscript ? (
          <p className="text-sm leading-snug text-slate-600 break-words">
            {lastTranscript.text}
          </p>
        ) : isRunning ? (
          <p className="text-xs text-slate-400">Listening...</p>
        ) : (
          <p className="text-xs text-slate-400">Press start to begin translating</p>
        )}

        {status === "translating" && (
          <div className="mt-2 flex items-center gap-1.5">
            <span className="inline-block animate-spin text-indigo-500 text-[11px]">&#x27F3;</span>
            <span className="text-[11px] font-medium text-indigo-600">Translating…</span>
          </div>
        )}

        {translationError && (
          <p className="mt-1.5 text-[11px] text-amber-600">
            Translation unavailable
          </p>
        )}
      </div>

      {/* Minimal footer with start/stop */}
      <footer className="flex shrink-0 items-center gap-1.5 border-t border-slate-100 px-2.5 py-1.5">
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          <MicIcon className={`h-3 w-3 shrink-0 ${active ? "text-emerald-500" : "text-slate-400"}`} />
          <span className="truncate text-[10px] font-medium text-slate-500">
            {isRunning ? meta.label : "Stopped"}
          </span>
        </div>
        {isRunning ? (
          <button
            type="button"
            onClick={onStop}
            className="app-no-drag flex h-6 items-center gap-1 rounded-md bg-rose-600 px-2 text-[11px] font-semibold text-white hover:bg-rose-700"
          >
            <StopIcon className="h-2.5 w-2.5" />
            Stop
          </button>
        ) : (
          <button
            type="button"
            onClick={onStart}
            className="app-no-drag flex h-6 items-center gap-1 rounded-md bg-emerald-600 px-2 text-[11px] font-semibold text-white hover:bg-emerald-700"
          >
            <PlayIcon className="h-2.5 w-2.5" />
            Start
          </button>
        )}
      </footer>
    </div>
  )
}
