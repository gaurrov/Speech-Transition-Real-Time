import type { WindowMode } from "../types"

export interface TranslatorPreferences {
  sourceLanguage: string
  targetLanguage: string
  windowMode: WindowMode
  sessionMode: "mock" | "live"
}

const STORAGE_KEY = "live-translator-preferences"

const DEFAULTS: TranslatorPreferences = {
  sourceLanguage: "auto",
  targetLanguage: "hi",
  windowMode: "expanded",
  sessionMode: "live",
}

export function loadPreferences(): TranslatorPreferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULTS
    const parsed = JSON.parse(raw) as Partial<TranslatorPreferences>
    return {
      ...DEFAULTS,
      ...parsed,
      windowMode: parsed.windowMode === "compact" ? "compact" : "expanded",
      sessionMode: parsed.sessionMode === "mock" ? "mock" : "live",
    }
  } catch {
    return DEFAULTS
  }
}

export function savePreferences(preferences: TranslatorPreferences): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences))
  } catch {
    // Persisting preferences is best-effort (e.g. private mode).
  }
}
