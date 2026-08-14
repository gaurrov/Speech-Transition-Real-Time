export type VADEvent =
  | { type: "speech_start"; timestamp: number }
  | { type: "speech_end"; timestamp: number }

export interface VADProvider {
  init(): Promise<void>
  start(stream: MediaStream): Promise<void>
  stop(): Promise<void>
  onEvent(callback: (event: VADEvent) => void): void
}
