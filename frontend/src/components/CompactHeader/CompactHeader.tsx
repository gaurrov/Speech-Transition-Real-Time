import type { ReactNode } from "react"
import type { SessionStatus, WindowMode } from "../../types"
import { ConnectionDot } from "../ConnectionDot"
import {
  ExpandIcon,
  GearIcon,
  GlobeIcon,
  MinimizeIcon,
  PinIcon,
  ShrinkIcon,
  XIcon,
} from "../icons"

export interface CompactHeaderProps {
  status: SessionStatus
  windowMode: WindowMode
  pinned: boolean
  inElectron: boolean
  /** Short source label, e.g. "EN" or "Auto Detect". */
  sourceLabel: string
  /** Short target label, e.g. "HI". */
  targetLabel: string
  onToggleWindowMode: () => void
  onOpenSettings: () => void
  onTogglePinned: () => void
  onMinimize: () => void
  onClose: () => void
}

function HeaderButton({
  onClick,
  label,
  title,
  danger = false,
  children,
}: {
  onClick: () => void
  label: string
  title: string
  danger?: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={title}
      className={`app-no-drag flex h-6 w-6 items-center justify-center rounded-md text-slate-500 transition-colors ${
        danger
          ? "hover:bg-rose-100 hover:text-rose-600"
          : "hover:bg-slate-100 hover:text-slate-700"
      }`}
    >
      {children}
    </button>
  )
}

export function CompactHeader({
  status,
  windowMode,
  pinned,
  inElectron,
  sourceLabel,
  targetLabel,
  onToggleWindowMode,
  onOpenSettings,
  onTogglePinned,
  onMinimize,
  onClose,
}: CompactHeaderProps) {
  const expanded = windowMode === "expanded"
  const title = expanded ? "Live Translator" : `${sourceLabel} → ${targetLabel}`

  return (
    <header className="app-drag flex shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-2.5 py-2">
      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-indigo-600 text-white">
        <GlobeIcon className="h-3.5 w-3.5" />
      </div>
      <h1 className="min-w-0 flex-1 truncate text-[13px] font-bold leading-tight text-slate-900">
        {title}
      </h1>

      <ConnectionDot status={status} showLabel={expanded} />

      <div className="flex items-center gap-0.5">
        <HeaderButton
          onClick={onToggleWindowMode}
          label={expanded ? "Switch to compact mode" : "Switch to expanded mode"}
          title={expanded ? "Compact mode" : "Expanded mode"}
        >
          {expanded ? <ShrinkIcon className="h-3.5 w-3.5" /> : <ExpandIcon className="h-3.5 w-3.5" />}
        </HeaderButton>

        <HeaderButton onClick={onOpenSettings} label="Open settings" title="Settings">
          <GearIcon className="h-3.5 w-3.5" />
        </HeaderButton>

        {inElectron && (
          <HeaderButton
            onClick={onTogglePinned}
            label={pinned ? "Unpin (disable always on top)" : "Pin (enable always on top)"}
            title={pinned ? "Pinned on top" : "Pin on top"}
          >
            <PinIcon className={`h-3.5 w-3.5 ${pinned ? "text-indigo-500" : ""}`} />
          </HeaderButton>
        )}

        {inElectron && (
          <HeaderButton onClick={onMinimize} label="Minimize" title="Minimize">
            <MinimizeIcon className="h-3.5 w-3.5" />
          </HeaderButton>
        )}

        {inElectron && (
          <HeaderButton onClick={onClose} label="Close translator" title="Close" danger>
            <XIcon className="h-3.5 w-3.5" />
          </HeaderButton>
        )}
      </div>
    </header>
  )
}
