import { AlertIcon, XIcon } from "../icons"

export interface ErrorBannerProps {
  message: string | null
  onDismiss: () => void
}

export function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  if (!message) return null
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-2 border-b border-rose-200 bg-rose-50 px-3 py-1.5 text-xs text-rose-700"
    >
      <div className="flex min-w-0 items-start gap-2">
        <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span className="break-words min-w-0">{message}</span>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss error"
        className="shrink-0 rounded p-0.5 hover:bg-rose-100"
      >
        <XIcon className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
