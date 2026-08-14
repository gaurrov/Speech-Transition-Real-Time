import type { LanguageOption } from "../types"

export interface LanguageDefinition extends LanguageOption {
  nativeName: string
}

export const AUTO_DETECT: LanguageOption = { code: "auto", label: "Auto Detect" }

const BASE_LANGUAGES: LanguageDefinition[] = [
  { code: "en", label: "English", nativeName: "English" },
  { code: "hi", label: "Hindi", nativeName: "हिन्दी" },
  { code: "ta", label: "Tamil", nativeName: "தமிழ்" },
  { code: "te", label: "Telugu", nativeName: "తెలుగు" },
  { code: "ml", label: "Malayalam", nativeName: "മലയാളം" },
  { code: "kn", label: "Kannada", nativeName: "ಕನ್ನಡ" },
  { code: "es", label: "Spanish", nativeName: "Español" },
  { code: "fr", label: "French", nativeName: "Français" },
  { code: "de", label: "German", nativeName: "Deutsch" },
  { code: "pt", label: "Portuguese", nativeName: "Português" },
  { code: "ja", label: "Japanese", nativeName: "日本語" },
  { code: "ko", label: "Korean", nativeName: "한국어" },
  { code: "zh", label: "Chinese", nativeName: "中文" },
  { code: "ar", label: "Arabic", nativeName: "العربية" },
  { code: "ru", label: "Russian", nativeName: "Русский" },
]

function parseExtraLanguages(): LanguageDefinition[] {
  const raw = import.meta.env.VITE_EXTRA_LANGUAGES
  if (!raw) return []
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(
        (item): item is Record<string, unknown> =>
          typeof item === "object" && item !== null,
      )
      .map((item) => ({
        code: String(item.code),
        label: String(item.label),
        nativeName:
          item.nativeName === undefined ? String(item.label) : String(item.nativeName),
      }))
  } catch {
    return []
  }
}

export const LANGUAGES: LanguageDefinition[] = [...BASE_LANGUAGES, ...parseExtraLanguages()]

export const SOURCE_LANGUAGES: LanguageOption[] = [AUTO_DETECT, ...LANGUAGES]

export function findLanguage(code: string): LanguageDefinition | undefined {
  return LANGUAGES.find((language) => language.code === code)
}

export function languageLabel(code: string): string {
  const found = findLanguage(code)
  return found ? found.label : code
}
