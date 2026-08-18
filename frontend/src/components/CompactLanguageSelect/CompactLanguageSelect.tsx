import type { LanguageOption } from "../../types"
import { ChevronDownIcon } from "../icons"

export interface CompactLanguageSelectProps {
  value: string
  options: LanguageOption[]
  onChange: (code: string) => void
  disabled?: boolean
  ariaLabel: string
}

export function CompactLanguageSelect({
  value,
  options,
  onChange,
  disabled = false,
  ariaLabel,
}: CompactLanguageSelectProps) {
  const selected = options.find((option) => option.code === value)
  return (
    <div className="relative flex-1">
      <select
        value={value}
        disabled={disabled}
        aria-label={ariaLabel}
        onChange={(event) => onChange(event.target.value)}
        className="w-full appearance-none truncate rounded-lg border border-slate-200 bg-slate-50 py-1.5 pl-3 pr-7 text-[12px] font-medium text-slate-700 transition-colors focus:border-indigo-400 focus:bg-white focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
      >
        {options.map((option) => (
          <option key={option.code} value={option.code}>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDownIcon
        className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400"
        aria-hidden="true"
      />
      {!selected && (
        <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-sm text-slate-400">
          Select…
        </span>
      )}
    </div>
  )
}
