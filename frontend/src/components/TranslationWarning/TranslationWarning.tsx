import { AlertIcon } from "../icons"

export interface TranslationWarningProps {
  message: string | null
}

export function TranslationWarning({ message }: TranslationWarningProps) {
  if (!message) return null
  return (
    <div
      role="status"
      className="flex items-start gap-2 border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-700"
    >
      <AlertIcon className="h-3.5 w-3.5 shrink-0 mt-0.5" />
      <span className="break-words min-w-0">{message}</span>
    </div>
  )
}
