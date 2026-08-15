import type { ReactNode } from "react"

export interface CompactPanelProps {
  title: string
  accent?: boolean
  right?: ReactNode
  children: ReactNode
  className?: string
}

export function CompactPanel({ title, accent = false, right, children, className = "" }: CompactPanelProps) {
  return (
    <section
      className={`flex min-h-0 flex-col overflow-hidden rounded-lg border bg-white shadow-sm ${className}`}
    >
      <header
        className={`flex shrink-0 items-center justify-between border-b px-3 py-1.5 ${
          accent ? "border-indigo-100 bg-indigo-50/60" : "border-slate-100"
        }`}
      >
        <h2
          className={`text-[11px] font-bold uppercase tracking-wider ${
            accent ? "text-indigo-500" : "text-slate-500"
          }`}
        >
          {title}
        </h2>
        {right}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2.5">{children}</div>
    </section>
  )
}
