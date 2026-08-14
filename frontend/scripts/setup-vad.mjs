/*
 * Provision the on-device Silero VAD runtime assets:
 *
 *   1. onnxruntime-web WASM files (no network) — copied from node_modules so
 *      the loader and its sibling .wasm keep exact filenames. The loader
 *      resolves its wasm relative to its own URL, so these must live under a
 *      stable path (public/vendor/onnx/) and be served with wasmPaths set to
 *      "/vendor/onnx/".
 *   2. The Silero VAD v5 ONNX model (network) — downloaded once to
 *      public/models/silero_vad.onnx. Skipped when already present. A failed
 *      download is non-fatal: the app falls back to a CDN copy at runtime and
 *      surfaces a clear VAD error otherwise.
 *
 * Wired to "predev" / "prebuild" so the runtime assets are always present
 * before Vite starts. Run manually with `npm run vad:setup`.
 */
import { copyFileSync, createWriteStream, existsSync, mkdirSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { Readable } from "node:stream"
import { fileURLToPath } from "node:url"

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const publicDir = resolve(repoRoot, "public")

const WASM_DIST = resolve(repoRoot, "node_modules", "onnxruntime-web", "dist")
const WASM_TARGET = resolve(publicDir, "vendor", "onnx")
const WASM_FILES = ["ort-wasm-simd-threaded.mjs", "ort-wasm-simd-threaded.wasm"]

const MODEL_TARGET = resolve(publicDir, "models")
const MODEL_FILENAME = "silero_vad.onnx"
const MODEL_SOURCES = [
  "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx",
  "https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx",
]

function log(message) {
  console.log(`[setup-vad] ${message}`)
}

function copyWasms() {
  if (!existsSync(WASM_DIST)) {
    log(`SKIP wasm copy: onnxruntime-web not installed (run npm install).`)
    return false
  }
  mkdirSync(WASM_TARGET, { recursive: true })
  for (const name of WASM_FILES) {
    const source = resolve(WASM_DIST, name)
    if (!existsSync(source)) {
      log(`WARN: expected ${name} in ${WASM_DIST} — onnxruntime-web layout may have changed.`)
      continue
    }
    copyFileSync(source, resolve(WASM_TARGET, name))
    log(`copied ${name}`)
  }
  return true
}

async function downloadModel() {
  const destination = resolve(MODEL_TARGET, MODEL_FILENAME)
  if (existsSync(destination)) {
    log(`model already present: public/models/${MODEL_FILENAME}`)
    return true
  }
  mkdirSync(MODEL_TARGET, { recursive: true })
  for (const url of MODEL_SOURCES) {
    log(`downloading Silero VAD v5 model from ${url} ...`)
    try {
      const response = await fetch(url, { redirect: "follow" })
      if (!response.ok) {
        log(`  download failed (HTTP ${response.status})`)
        continue
      }
      await new Promise((resolveDone, rejectDone) => {
        const out = createWriteStream(destination)
        Readable.fromWeb(response.body).pipe(out)
        out.on("finish", () => {
          out.close()
          resolveDone()
        })
        out.on("error", rejectDone)
      })
      log(`saved public/models/${MODEL_FILENAME}`)
      return true
    } catch (cause) {
      log(`  download error: ${cause.message}`)
    }
  }
  log(`WARN: could not download the VAD model. The app will try a CDN copy at runtime.`)
  return false
}

copyWasms()
downloadModel()
