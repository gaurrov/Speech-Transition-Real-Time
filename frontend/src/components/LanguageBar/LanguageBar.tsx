import type { LanguageOption } from "../../types"
import { CompactLanguageSelect } from "../CompactLanguageSelect"
import { ArrowRightIcon } from "../icons"

export interface LanguageBarProps {
  sourceValue: string
  targetValue: string
  sourceOptions: LanguageOption[]
  targetOptions: LanguageOption[]
  onSourceChange: (code: string) => void
  onTargetChange: (code: string) => void
  disabled?: boolean
}

export function LanguageBar({
  sourceValue,
  targetValue,
  sourceOptions,
  targetOptions,
  onSourceChange,
  onTargetChange,
  disabled = false,
}: LanguageBarProps) {
  return (
    <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5">
      <CompactLanguageSelect
        value={sourceValue}
        options={sourceOptions}
        onChange={onSourceChange}
        disabled={disabled}
        ariaLabel="Source language"
      />
      <ArrowRightIcon className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
      <CompactLanguageSelect
        value={targetValue}
        options={targetOptions}
        onChange={onTargetChange}
        disabled={disabled}
        ariaLabel="Target language"
      />
    </div>
  )
}
