# Audio Capture

The translator captures audio on the client and streams it through a single
pipeline (AudioWorklet → Silero VAD → WebSocket → FastAPI → ASR → translation
→ Electron UI). The capture *source* is swappable: either your microphone or
system/meeting audio. Both feed the **same** pipeline — nothing downstream
changes.

- `frontend/src/providers/audio/sources.ts` defines the `AudioSource`
  abstraction, `MicrophoneAudioSource`, and `SystemAudioSource`.
- `frontend/src/hooks/useAudioCapture.ts` owns acquisition and lifecycle and
  calls `source.acquire()` to get a `MediaStream`.
- The picker lives in Settings → **Audio source**.

## Microphone capture

Default and universally supported.

- Uses `navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true,
  noiseSuppression: true, autoGainControl: true } })`.
- The browser prompts for microphone permission on first use.
- Works in a plain browser tab and in Electron.

## System audio (meeting / browser) capture

Translates what a meeting or browser window is playing — e.g. the other
participants in Google Meet — without a microphone.

### How it works (Windows, Electron)

1. The renderer calls `navigator.mediaDevices.getDisplayMedia({ video: false,
   audio: true })` (`SystemAudioSource.acquire()` in
   `frontend/src/providers/audio/sources.ts`).
2. Electron's main process fulfills the request via
   `session.setDisplayMediaRequestHandler` returning `{ audio: "loopback" }`
   (`electron/main.js`). That produces a "System audio" track carrying the
   device's output mix.
3. The stream flows through the normal capture pipeline. Sample rate is
   48 kHz, resampled to 16 kHz mono by the worklet.

This is the **only** supported web-API mechanism on current Chromium/Windows.
The historical alternatives are gone: `getUserMedia` with
`chromeMediaSource: "desktop"` + `chromeMediaSourceId` terminates the renderer
(`DESKTOP_CAPTURER_INVALID_OR_UNKNOWN_ID`, Electron #46369), and
`desktopCapturer` sources report `audio: false` for every window on Windows.
Whole-system loopback is therefore the honest, working option: it captures
everything the PC plays, including the meeting audio. Per-window selection is
not possible via web APIs on Windows — see limitations below.

### Supported platforms

| Platform | System audio | Mechanism |
|---|---|---|
| Windows | Yes | `getDisplayMedia` + handler `{ audio: "loopback" }` — whole-system output mix. |
| macOS / Linux | No (Chromium limitation) | `desktopCapturer` exposes no per-window audio; the Chromium sandbox blocks it. Mic capture remains fully functional. |

The abstraction is ready; enabling macOS/Linux would mean wiring a different
capture mechanism (e.g. screen recording with audio) behind the same
`AudioSource` interface. `window.desktop.getAudioSources()` / the
`audio:list-sources` IPC (Electron `desktopCapturer`) is kept for platforms
that expose per-source audio and for diagnostics; Windows ignores it for
capture.

### Permissions

- **Windows:** no extra OS-level prompt for system audio; `getDisplayMedia`
  is fulfilled by the app's own handler. The OS lets any session record its
  output mix, so there is nothing to request.
- **macOS/Linux:** microphone-only fallback today; granting screen-recording
  permissions would be required before any future system-audio path.
- The app never bypasses OS/browser security. The system-audio request goes
  through the standard `getDisplayMedia` flow (Electron-fulfilled) and the
  Electron renderer stays sandboxed (`contextIsolation` + `sandbox: true`).

### UI states

- **Microphone** — normal mic flow.
- **System audio** selected but not running in Electron: amber note telling
  the user to switch back to Microphone in a plain browser tab.
- **In Electron:** a slate note explaining that capture is the whole-system
  output mix (Chromium exposes no per-window audio on Windows) plus a tip to
  start the meeting first.
- **Error at start:** red alert from `AudioSourceError` (e.g. not granted,
  not supported, not in Electron).
- While a session is running the source selector is **disabled** — stop the
  session, change source, start again. The **Listening** status pill shows
  the active source label so you can tell which capture is live.

## Echo / feedback avoidance

- The translator window **never outputs audible audio**: the worklet routes
  the mic/mix to its `output` node but `muteGain.gain` is 0, so nothing is
  played back. Its own output therefore cannot loop back into a capture.
- Loopback captures **everything** the PC plays. If meeting speakers play
  other participants' audio out loud, that audio will be captured — use a
  **headset** so "system audio" contains only the far-end participants.
- Voice-processing (AEC/NS/AGC) is not applied to the system mix; the capture
  is a plain output mix.
- If you ever re-enable audible output (e.g. synthesized captions), you must
  re-examine loop paths — that is the documented risk boundary for feedback.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Requires the Electron companion app" | System audio needs the Electron build; plain-browser tabs can only use the mic. |
| System mode shows no translations | Confirm something is actually playing on the PC (start the meeting/video first). Check the Listening pill shows "System audio". |
| Mic mode stopped working | Switch the picker back to **Microphone** — `capture.start()` resolves the source from Settings. |
| Switched source while running | Stop the session first — the selector is disabled while running. |
| macOS/Linux system audio missing | Expected limitation; use Microphone (see table above). |
| Capture is unexpectedly loud/includes own PC sounds | That's the whole-system mix by design — mute unrelated apps or use a headset. |

## Manual test checklist

1. **Mic baseline:** with the source set to Microphone, press Start and speak —
   captions appear. Confirms existing mic mode is unbroken.
2. **System audio:** Settings → Audio source → System audio → play audio
   somewhere (browser video, a meeting, another app) → Start. The Listening
   pill shows "System audio"; translations arrive while the floating window
   is visible.
3. **Switch back:** Stop → pick Microphone → Start. Mic mode still works.
4. **No echo:** confirm no audible feedback loop while system capture runs.
