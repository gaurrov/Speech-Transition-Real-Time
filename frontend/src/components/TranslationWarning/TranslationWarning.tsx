import { AlertIcon } from "../icons"

export interface TranslationWarningProps {
  message: string | null
}

export function TranslationWarning({ message }: TranslationWarningProps) {
  if (!message) return null
  return (
    <div
      role="status"
      className="flex items-center gap-2 border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-700"
    >
      <AlertIcon className="h-4 w-4 shrink-0" />
      <span>{message}</span>
    </div>
  )
}
