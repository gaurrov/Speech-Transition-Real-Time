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
      className="flex items-start justify-between gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700"
    >
      <div className="flex items-start gap-2">
        <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{message}</span>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss error"
        className="rounded p-0.5 hover:bg-rose-100"
      >
        <XIcon className="h-4 w-4" />
      </button>
    </div>
  )
}
