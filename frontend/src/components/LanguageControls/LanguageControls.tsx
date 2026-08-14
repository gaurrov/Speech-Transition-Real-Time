import { languageLabel } from "../../config/languages"
import type { LanguageOption } from "../../types"
import { ArrowRightIcon } from "../icons"
import { SearchableLanguageSelect } from "../SearchableLanguageSelect"

export interface LanguageControlsProps {
  sourceValue: string
  targetValue: string
  sourceOptions: LanguageOption[]
  targetOptions: LanguageOption[]
  onSourceChange: (code: string) => void
  onTargetChange: (code: string) => void
  disabled?: boolean
}

export function LanguageControls({
  sourceValue,
  targetValue,
  sourceOptions,
  targetOptions,
  onSourceChange,
  onTargetChange,
  disabled = false,
}: LanguageControlsProps) {
  const sourceLabel = sourceValue === "auto" ? "Auto Detect" : languageLabel(sourceValue)

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
        <SearchableLanguageSelect
          id="source-language"
          label="Source language"
          value={sourceValue}
          options={sourceOptions}
          onChange={onSourceChange}
          disabled={disabled}
          placeholder="Auto Detect"
        />
        <div className="hidden pb-2 text-slate-300 sm:block" aria-hidden="true">
          <ArrowRightIcon className="h-4 w-4" />
        </div>
        <SearchableLanguageSelect
          id="target-language"
          label="Target language"
          value={targetValue}
          options={targetOptions}
          onChange={onTargetChange}
          disabled={disabled}
        />
      </div>
      <p className="text-xs text-slate-500">
        Listening in: <span className="font-medium text-slate-700">{sourceLabel}</span> ·{" "}
        Translating to: <span className="font-medium text-slate-700">{languageLabel(targetValue)}</span>
      </p>
    </div>
  )
}
