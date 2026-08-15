"use strict"

/**
 * Electron main process for the Live Translator desktop companion window.
 *
 * Responsibilities:
 *   - Create and manage the compact, always-on-top translator window.
 *   - Persist window size/position between launches (window-state.json).
 *   - Expose a minimal IPC surface to the preload script (minimize, close,
 *     pin/unpin always-on-top) — nothing else leaks into the renderer.
 *   - Auto-start the FastAPI backend when it is not already running, so the
 *     packaged/dev app "just works". Set TRANSLATOR_EXTERNAL_BACKEND=true to
 *     run the backend yourself.
 *
 * Security: contextIsolation enabled, nodeIntegration disabled, sandbox
 * enabled. The renderer can only reach the host via the narrow APIs exposed
 * in preload.js.
 */

const { app, BrowserWindow, ipcMain, screen } = require("electron")
const { spawn } = require("child_process")
const fs = require("node:fs")
const net = require("node:net")
const path = require("node:path")

const DEFAULT_WIDTH = 420
const DEFAULT_HEIGHT = 600
const MIN_WIDTH = 320
const MIN_HEIGHT = 480

const BACKEND_PORT = Number(process.env.TRANSLATOR_BACKEND_PORT || 8000)
const BACKEND_HOST = "127.0.0.1"
const AUTOSTART_BACKEND = process.env.TRANSLATOR_EXTERNAL_BACKEND !== "true"

let mainWindow = null
let backendProcess = null

// ---------------------------------------------------------------------------
// Window state persistence
// ---------------------------------------------------------------------------

function windowStateFile() {
  return path.join(app.getPath("userData"), "window-state.json")
}

function loadWindowState() {
  const fallback = { width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT }
  try {
    const raw = fs.readFileSync(windowStateFile(), "utf8")
    const state = JSON.parse(raw)
    const width = Number(state.width) || fallback.width
    const height = Number(state.height) || fallback.height
    if (width < MIN_WIDTH || height < MIN_HEIGHT) return fallback
    return { ...fallback, width, height, x: state.x, y: state.y }
  } catch {
    return fallback
  }
}

function isBoundsOnScreen(bounds) {
  const { x, y, width, height } = bounds
  if (typeof x !== "number" || typeof y !== "number") return false
  return screen.getAllDisplays().some((display) => {
    const area = display.workArea
    return (
      x < area.x + area.width &&
      x + width > area.x &&
      y < area.y + area.height &&
      y + height > area.y
    )
  })
}

function saveWindowState(win) {
  if (win.isMaximized() || win.isFullScreen() || win.isMinimized()) return
  const bounds = win.getBounds()
  const state = { width: bounds.width, height: bounds.height, x: bounds.x, y: bounds.y }
  try {
    fs.writeFileSync(windowStateFile(), JSON.stringify(state, null, 2))
  } catch {
    // Best-effort: failing to persist the window position is not fatal.
  }
}

// ---------------------------------------------------------------------------
// Backend management
// ---------------------------------------------------------------------------

function checkPortOpen(host, port, timeoutMs = 800) {
  return new Promise((resolve) => {
    const socket = new net.Socket()
    const onDone = (result) => {
      socket.removeAllListeners()
      socket.destroy()
      resolve(result)
    }
    socket.setTimeout(timeoutMs)
    socket.once("connect", () => onDone(true))
    socket.once("timeout", () => onDone(false))
    socket.once("error", () => onDone(false))
    socket.connect(port, host)
  })
}

function backendCandidates() {
  const backendDir = path.join(__dirname, "..", "backend")
  const venvPython = process.platform === "win32"
    ? path.join(backendDir, ".venv", "Scripts", "python.exe")
    : path.join(backendDir, ".venv", "bin", "python")
  const args = ["-m", "uvicorn", "app.main:app", "--host", BACKEND_HOST, "--port", String(BACKEND_PORT)]
  return [
    { command: venvPython, args, cwd: backendDir },
    { command: "uv", args: ["run", ...args], cwd: backendDir },
    { command: "python", args, cwd: backendDir },
  ]
}

async function startBackend() {
  if (!AUTOSTART_BACKEND) return
  const alreadyRunning = await checkPortOpen(BACKEND_HOST, BACKEND_PORT)
  if (alreadyRunning) {
    console.log(`[backend] already running on ${BACKEND_HOST}:${BACKEND_PORT}, skipping auto-start`)
    return
  }
  for (const candidate of backendCandidates()) {
    try {
      const child = spawn(candidate.command, candidate.args, {
        cwd: candidate.cwd,
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      })
      child.stdout.on("data", (chunk) => process.stdout.write(`[backend] ${chunk}`))
      child.stderr.on("data", (chunk) => process.stderr.write(`[backend] ${chunk}`))
      child.on("error", (error) => {
        console.warn(`[backend] failed to start ${candidate.command}: ${error.message}`)
      })
      child.on("exit", (code) => {
        console.log(`[backend] exited with code ${code}`)
        if (backendProcess === child) backendProcess = null
      })
      backendProcess = child
      console.log(`[backend] starting ${candidate.command} on ${BACKEND_HOST}:${BACKEND_PORT}`)
      return
    } catch {
      // Try the next candidate.
    }
  }
  console.warn("[backend] could not auto-start backend; is it running already?")
}

function stopBackend() {
  if (!backendProcess) return
  try {
    backendProcess.kill()
  } catch {
    // Already gone.
  }
  backendProcess = null
}

// ---------------------------------------------------------------------------
// Window creation
// ---------------------------------------------------------------------------

function createWindow() {
  const state = loadWindowState()
  const initialBounds = { width: state.width, height: state.height }
  if (typeof state.x === "number" && typeof state.y === "number") {
    const proposed = { ...initialBounds, x: state.x, y: state.y }
    if (isBoundsOnScreen(proposed)) {
      initialBounds.x = state.x
      initialBounds.y = state.y
    }
  }

  mainWindow = new BrowserWindow({
    ...initialBounds,
    minWidth: MIN_WIDTH,
    minHeight: MIN_HEIGHT,
    show: false,
    frame: false,
    resizable: true,
    alwaysOnTop: true,
    backgroundColor: "#0f172a",
    title: "Live Translator",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  })

  mainWindow.on("ready-to-show", () => {
    mainWindow?.show()
  })

  // "floating" keeps the translator above normal windows (Zoom/Meet/Teams)
  // without covering fullscreen apps or system overlays.
  mainWindow.setAlwaysOnTop(true, "floating")

  mainWindow.on("resize", scheduleSave)
  mainWindow.on("move", scheduleSave)
  mainWindow.on("closed", () => {
    mainWindow = null
  })

  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL)
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "frontend", "dist", "index.html"))
  }

  return mainWindow
}

// Debounced save so rapid drag/resize does not hammer the disk.
let saveTimer = null
function scheduleSave() {
  if (saveTimer !== null) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    saveTimer = null
    if (mainWindow) saveWindowState(mainWindow)
  }, 500)
}

// ---------------------------------------------------------------------------
// IPC — the only surface the renderer can touch
// ---------------------------------------------------------------------------

function registerIpc() {
  ipcMain.on("window:minimize", () => {
    mainWindow?.minimize()
  })

  ipcMain.on("window:close", () => {
    mainWindow?.close()
  })

  ipcMain.handle("window:toggle-always-on-top", () => {
    if (!mainWindow) return true
    const next = !mainWindow.isAlwaysOnTop()
    mainWindow.setAlwaysOnTop(next, "floating")
    mainWindow.webContents.send("window:always-on-top-changed", next)
    return next
  })

  ipcMain.handle("window:is-always-on-top", () => {
    return mainWindow ? mainWindow.isAlwaysOnTop() : true
  })
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(async () => {
  registerIpc()
  await startBackend()
  createWindow()

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on("window-all-closed", () => {
  app.quit()
})

app.on("will-quit", () => {
  stopBackend()
})
