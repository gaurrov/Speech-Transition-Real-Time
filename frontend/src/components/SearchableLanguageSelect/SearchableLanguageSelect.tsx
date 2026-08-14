import { useEffect, useMemo, useRef, useState } from "react"
import type { LanguageOption } from "../../types"
import { ChevronDownIcon, SearchIcon } from "../icons"

export interface SearchableLanguageSelectProps {
  id: string
  label: string
  value: string
  options: LanguageOption[]
  onChange: (code: string) => void
  disabled?: boolean
  placeholder?: string
}

export function SearchableLanguageSelect({
  id,
  label,
  value,
  options,
  onChange,
  disabled = false,
  placeholder = "Select a language",
}: SearchableLanguageSelectProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [activeIndex, setActiveIndex] = useState(0)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const searchRef = useRef<HTMLInputElement | null>(null)

  const selected = options.find((option) => option.code === value)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter((option) =>
      [option.label, option.code].some((part) => part.toLowerCase().includes(q)),
    )
  }, [options, query])

  useEffect(() => {
    if (open) {
      setQuery("")
      setActiveIndex(0)
      searchRef.current?.focus()
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false)
        return
      }
      if (event.key === "ArrowDown") {
        event.preventDefault()
        setActiveIndex((index) => Math.min(index + 1, filtered.length - 1))
        return
      }
      if (event.key === "ArrowUp") {
        event.preventDefault()
        setActiveIndex((index) => Math.max(index - 1, 0))
        return
      }
      if (event.key === "Enter" && filtered[activeIndex]) {
        event.preventDefault()
        onChange(filtered[activeIndex].code)
        setOpen(false)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [open, filtered, activeIndex, onChange])

  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    window.addEventListener("pointerdown", onPointerDown)
    return () => window.removeEventListener("pointerdown", onPointerDown)
  }, [])

  return (
    <div ref={rootRef} className="relative flex w-56 flex-col gap-1">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <button
        id={id}
        type="button"
        disabled={disabled}
        onClick={() => setOpen((isOpen) => !isOpen)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex items-center justify-between gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-left text-sm shadow-sm focus:border-indigo-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
      >
        <span className={selected ? "truncate text-slate-900" : "truncate text-slate-400"}>
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDownIcon
          className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div className="absolute top-full z-20 mt-1 w-56 overflow-hidden rounded-md border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
            <SearchIcon className="h-4 w-4 shrink-0 text-slate-400" />
            <input
              ref={searchRef}
              type="text"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                setActiveIndex(0)
              }}
              placeholder="Search languages…"
              aria-label={`Search ${label.toLowerCase()}`}
              className="w-full bg-transparent text-sm text-slate-700 outline-none placeholder:text-slate-400"
            />
          </div>
          <ul role="listbox" aria-labelledby={id} className="max-h-56 overflow-y-auto py-1">
            {filtered.map((option, index) => (
              <li
                key={option.code}
                role="option"
                aria-selected={option.code === value}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => {
                  onChange(option.code)
                  setOpen(false)
                }}
                className={`flex cursor-pointer items-center justify-between px-3 py-2 text-sm ${
                  index === activeIndex
                    ? "bg-indigo-50 text-indigo-700"
                    : "text-slate-700"
                }`}
              >
                <span>{option.label}</span>
                {option.code === value && <span className="text-indigo-500">✓</span>}
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="px-3 py-2 text-sm text-slate-400">
                No languages match &quot;{query}&quot;
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  )
}
