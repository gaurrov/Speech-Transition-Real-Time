export interface AudioSourceOption {
  id: string
  label: string
  available: boolean
  description?: string
}

export const AUDIO_SOURCES: AudioSourceOption[] = [
  {
    id: "microphone",
    label: "Microphone",
    available: true,
    description: "Default input device",
  },
  {
    id: "system",
    label: "Browser / System audio",
    available: false,
    description: "Coming soon",
  },
]
