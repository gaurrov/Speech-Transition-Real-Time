import type { LatencyReport, SessionStatus } from "../../types"
import { ConnectionStatus } from "../ConnectionStatus"
import { LatencyIndicator } from "../LatencyIndicator"
import { GearIcon, GlobeIcon } from "../icons"

export interface HeaderProps {
  status: SessionStatus
  latency: LatencyReport | null
  latencyVisible: boolean
  onOpenSettings: () => void
}

export function Header({
  status,
  latency,
  latencyVisible,
  onOpenSettings,
}: HeaderProps) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-sm">
          <GlobeIcon className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-lg font-bold leading-tight text-slate-900">
            Real-Time Translator
          </h1>
          <p className="text-xs text-slate-500">Live captions for online meetings</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <LatencyIndicator latency={latency} visible={latencyVisible} />
        <ConnectionStatus status={status} />
        <button
          type="button"
          onClick={onOpenSettings}
          aria-label="Open settings"
          title="Settings"
          className="flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-700"
        >
          <GearIcon className="h-4 w-4" />
        </button>
      </div>
    </header>
  )
}
