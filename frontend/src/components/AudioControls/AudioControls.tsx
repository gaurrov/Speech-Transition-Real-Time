import type { AudioSourceOption } from "../../config/audioSources"
import { MicIcon, MicOffIcon, PlayIcon, StopIcon } from "../icons"

export interface AudioControlsProps {
  isRunning: boolean
  isCapturing: boolean
  audioSource: string
  audioSources: AudioSourceOption[]
  onAudioSourceChange: (id: string) => void
  onStart: () => void
  onStop: () => void
  disabled?: boolean
}

export function AudioControls({
  isRunning,
  isCapturing,
  audioSource,
  audioSources,
  onAudioSourceChange,
  onStart,
  onStop,
  disabled = false,
}: AudioControlsProps) {
  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
      <button
        type="button"
        onClick={isRunning ? onStop : onStart}
        disabled={disabled}
        className={`flex items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
          isRunning
            ? "bg-rose-600 hover:bg-rose-700"
            : "bg-emerald-600 hover:bg-emerald-700"
        }`}
      >
        {isRunning ? <StopIcon className="h-4 w-4" /> : <PlayIcon className="h-4 w-4" />}
        {isRunning ? "Stop Translation" : "Start Translation"}
      </button>

      <div
        role="status"
        aria-live="polite"
        className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-sm ${
          isCapturing
            ? "bg-emerald-50 text-emerald-700"
            : "bg-slate-100 text-slate-500"
        }`}
      >
        {isCapturing ? <MicIcon className="h-4 w-4" /> : <MicOffIcon className="h-4 w-4" />}
        <span className="font-medium">{isCapturing ? "Mic active" : "Mic off"}</span>
      </div>

      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
          Audio source
        </span>
        <select
          value={audioSource}
          disabled={disabled}
          onChange={(event) => onAudioSourceChange(event.target.value)}
          className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
        >
          {audioSources.map((source) => (
            <option key={source.id} value={source.id} disabled={!source.available}>
              {source.available
                ? source.label
                : `${source.label} (${source.description ?? "soon"})`}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
