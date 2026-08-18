import type { ReactNode } from "react"
import type { SessionStatus, WindowMode } from "../../types"
import {
  GearIcon,
  GlobeIcon,
  MinimizeIcon,
  PinIcon,
  ShrinkIcon,
  XIcon,
} from "../icons"
import { statusMeta } from "../status"

function OverlayIcon({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <rect x="10" y="11" width="12" height="10" rx="1" ry="1" fill="currentColor" opacity="0.15" stroke="currentColor" />
    </svg>
  )
}

export interface CompactHeaderProps {
  status: SessionStatus
  windowMode: WindowMode
  pinned: boolean
  inElectron: boolean
  sourceLabel: string
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
      className={`app-no-drag flex h-5 w-5 items-center justify-center rounded text-slate-400 transition-colors ${
        danger
          ? "hover:bg-rose-50 hover:text-rose-600"
          : "hover:bg-slate-100 hover:text-slate-600"
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
  const meta = statusMeta(status)

  return (
    <header className="app-drag flex shrink-0 items-center gap-1.5 border-b border-slate-200/80 bg-slate-50/50 px-2.5 py-1.5">
      {/* App icon + language pair */}
      <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-indigo-600 text-white">
        <GlobeIcon className="h-3 w-3" />
      </div>
      <span className="min-w-0 truncate text-[12px] font-semibold text-slate-700">
        {sourceLabel}
      </span>
      <span className="text-[10px] text-slate-300">→</span>
      <span className="min-w-0 truncate text-[12px] font-semibold text-slate-700">
        {targetLabel}
      </span>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Connection status */}
      <div
        role="status"
        aria-live="polite"
        className="flex items-center gap-1"
        title={meta.label}
      >
        <span className={`h-2 w-2 rounded-full ${meta.dotClass}`} aria-hidden="true" />
        {expanded && (
          <span className={`text-[10px] font-medium ${meta.textClass}`}>{meta.label}</span>
        )}
      </div>

      {/* Controls */}
      <div className="flex items-center gap-0.5">
        <HeaderButton
          onClick={onOpenSettings}
          label="Open settings"
          title="Settings"
        >
          <GearIcon className="h-3 w-3" />
        </HeaderButton>

        <HeaderButton
          onClick={onToggleWindowMode}
          label={expanded ? "Switch to compact mode" : "Switch to overlay mode"}
          title={expanded ? "Compact" : "Overlay"}
        >
          {expanded ? (
            <ShrinkIcon className="h-3 w-3" />
          ) : (
            <OverlayIcon className="h-3 w-3" />
          )}
        </HeaderButton>

        {inElectron && (
          <HeaderButton
            onClick={onTogglePinned}
            label={pinned ? "Unpin" : "Pin on top"}
            title={pinned ? "Pinned" : "Pin"}
          >
            <PinIcon className={`h-3 w-3 ${pinned ? "text-indigo-500" : ""}`} />
          </HeaderButton>
        )}

        {inElectron && (
          <HeaderButton onClick={onMinimize} label="Minimize" title="Minimize">
            <MinimizeIcon className="h-3 w-3" />
          </HeaderButton>
        )}

        {inElectron && (
          <HeaderButton onClick={onClose} label="Close" title="Close" danger>
            <XIcon className="h-3 w-3" />
          </HeaderButton>
        )}
      </div>
    </header>
  )
}
