/**
 * Audio source abstraction.
 *
 * Both sources (microphone and system/meeting audio) produce a MediaStream
 * that flows through the SAME pipeline (AudioWorklet → PCM16 chunks → VAD →
 * WebSocket → FastAPI → Deepgram → Translation → Electron UI). Only the
 * acquisition differs; nothing downstream is duplicated.
 *
 * System audio (Windows, Electron 33+): the renderer requests
 * `getDisplayMedia({ video: false, audio: true })`, which Electron's main
 * process fulfills via `session.setDisplayMediaRequestHandler` returning
 * `{ audio: "loopback" }`. That yields a "System audio" track carrying the
 * device output (meeting/browser audio). This is the only supported web-API
 * path: `getUserMedia` with `chromeMediaSource: "desktop"` terminates the
 * renderer on this Chromium (DESKTOP_CAPTURER_INVALID_OR_UNKNOWN_ID), and
 * `desktopCapturer` sources report no per-window audio on Windows.
 *
 * `listSystemAudioSources()` / the `audio:list-sources` IPC remain available
 * for platforms that DO expose per-source audio (e.g. macOS ScreenCaptureKit
 * via desktopCapturer) — the abstraction is ready; the Windows UI selects
 * whole-system loopback instead.
 */

export type AudioSourceKind = "microphone" | "system"

/** A capturable desktop source reported by Electron's desktopCapturer. */
export interface SystemAudioWindow {
  id: string
  name: string
  kind: "window" | "screen"
  /** Whether audio can be captured from this source (Windows Chromium: always false). */
  audio: boolean
}

export class AudioSourceError extends Error {
  constructor(
    message: string,
    /** Stable machine-readable code for tests/UI branching. */
    readonly code: string,
  ) {
    super(message)
    this.name = "AudioSourceError"
  }
}

export interface AudioSource {
  readonly kind: AudioSourceKind
  /** Human-readable label for status badges / diagnostics. */
  readonly label: string
  /** Acquire a MediaStream for this source. Rejects with AudioSourceError. */
  acquire(): Promise<MediaStream>
}

export class MicrophoneAudioSource implements AudioSource {
  readonly kind: AudioSourceKind = "microphone"
  readonly label = "Microphone"

  async acquire(): Promise<MediaStream> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new AudioSourceError(
        "Microphone access is not supported in this browser.",
        "unsupported",
      )
    }
    try {
      return await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
    } catch (cause) {
      throw micError(cause)
    }
  }
}

export class SystemAudioSource implements AudioSource {
  readonly kind: AudioSourceKind = "system"
  readonly label = "System audio"

  async acquire(): Promise<MediaStream> {
    if (!window.desktop?.isElectron) {
      throw new AudioSourceError(
        "System audio requires the Electron companion app. Use Microphone here.",
        "not_electron",
      )
    }
    if (!navigator.mediaDevices?.getDisplayMedia) {
      throw new AudioSourceError(
        "This browser cannot capture system audio.",
        "unsupported",
      )
    }
    try {
      // Electron main's setDisplayMediaRequestHandler responds with
      // `{ audio: "loopback" }`, giving a track of the device output.
      return await navigator.mediaDevices.getDisplayMedia({
        video: false,
        audio: true,
      })
    } catch (cause) {
      throw systemError(cause)
    }
  }
}

export function createAudioSource(kind: AudioSourceKind): AudioSource {
  return kind === "system" ? new SystemAudioSource() : new MicrophoneAudioSource()
}

/**
 * List capturable desktop sources (windows + screen) via the Electron bridge.
 *
 * Reserved for platforms that report per-source audio (macOS/Linux). On
 * Windows, Chromium reports `audio: false` for every source, so system capture
 * uses whole-desktop loopback instead (see `SystemAudioSource`).
 */
export async function listSystemAudioSources(): Promise<SystemAudioWindow[]> {
  if (!window.desktop) return []
  try {
    return await window.desktop.getAudioSources()
  } catch {
    return []
  }
}

function micError(cause: unknown): AudioSourceError {
  if (cause instanceof DOMException) {
    switch (cause.name) {
      case "NotAllowedError":
        return new AudioSourceError(
          "Microphone permission was denied. Allow microphone access in your browser and try again.",
          "permission_denied",
        )
      case "NotFoundError":
        return new AudioSourceError("No microphone was found on this device.", "not_found")
      case "NotReadableError":
        return new AudioSourceError(
          "The microphone is in use by another application or cannot be read.",
          "not_readable",
        )
      case "OverconstrainedError":
        return new AudioSourceError(
          "No microphone matching the requested settings was found.",
          "overconstrained",
        )
      default:
        return new AudioSourceError(cause.message || "Unable to access the microphone.", "generic")
    }
  }
  return new AudioSourceError(
    cause instanceof Error ? cause.message : "Unable to access the microphone.",
    "generic",
  )
}

function systemError(cause: unknown): AudioSourceError {
  if (cause instanceof DOMException) {
    switch (cause.name) {
      case "NotAllowedError":
        return new AudioSourceError(
          "System-audio capture was not granted. Try again from the Start button.",
          "permission_denied",
        )
      case "NotSupportedError":
        return new AudioSourceError(
          "System audio is not supported by this build/platform. Use Microphone instead.",
          "not_supported",
        )
      case "SecurityError":
        return new AudioSourceError(
          "System-audio capture is blocked in this environment.",
          "security",
        )
      default:
        return new AudioSourceError(
          cause.message || "Unable to capture system audio.",
          "generic",
        )
    }
  }
  return new AudioSourceError(
    cause instanceof Error ? cause.message : "Unable to capture system audio.",
    "generic",
  )
}
