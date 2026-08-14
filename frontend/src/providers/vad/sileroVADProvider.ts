import type { VADEvent, VADProvider } from "./types"

export class SileroVADProvider implements VADProvider {
  async init(): Promise<void> {
    throw new Error("SileroVADProvider.init is not yet implemented")
  }

  async start(_stream: MediaStream): Promise<void> {
    throw new Error("SileroVADProvider.start is not yet implemented")
  }

  async stop(): Promise<void> {
    throw new Error("SileroVADProvider.stop is not yet implemented")
  }

  onEvent(_callback: (event: VADEvent) => void): void {}
}
