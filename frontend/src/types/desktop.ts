/**
 * Typed surface for the Electron preload bridge (window.desktop).
 *
 * `window.desktop` is only defined when the renderer is running inside the
 * Electron companion window. In a plain browser tab (Vite dev) it is
 * undefined, and the UI degrades to browser-only behavior (no OS window
 * controls, no pin button).
 */

export interface DesktopBridge {
  readonly isElectron: true
  readonly platform: string
  minimize: () => void
  close: () => void
  toggleAlwaysOnTop: () => Promise<boolean>
  isAlwaysOnTop: () => Promise<boolean>
  onAlwaysOnTopChanged: (callback: (pinned: boolean) => void) => () => void
}

declare global {
  interface Window {
    desktop?: DesktopBridge
  }
}
