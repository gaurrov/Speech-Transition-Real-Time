/**
 * Typed surface for the Electron preload bridge (window.desktop).
 *
 * `window.desktop` is only defined when the renderer is running inside the
 * Electron companion window. In a plain browser tab (Vite dev) it is
 * undefined, and the UI degrades to browser-only behavior (no OS window
 * controls, no pin button).
 */

import type { SystemAudioWindow } from "../providers/audio/sources"

export interface DesktopBridge {
  readonly isElectron: true
  readonly platform: string
  minimize: () => void
  close: () => void
  toggleAlwaysOnTop: () => Promise<boolean>
  isAlwaysOnTop: () => Promise<boolean>
  onAlwaysOnTopChanged: (callback: (pinned: boolean) => void) => () => void
  /**
   * List desktop capture sources (windows + screen). Only sources that report
   * `audio: true` can feed system-audio capture. Windows-only in practice.
   */
  getAudioSources: () => Promise<SystemAudioWindow[]>
}

declare global {
  interface Window {
    desktop?: DesktopBridge
  }
}
