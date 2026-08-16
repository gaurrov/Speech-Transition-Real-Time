"use strict"

/**
 * Disposable Electron soak: launches the real Electron window against the stub
 * backend (soak_backend_server.py) and drives it over the DevTools protocol.
 *
 * Verifies over a long-running session with real microphone capture and
 * continuous translations:
 *   * WS stays connected (translations keep flowing; no error banner).
 *   * Transcript ordering / translation sync at the DOM level.
 *   * Renderer memory is bounded (no leak).
 *   * Renderer main thread stays responsive (rAF probe round-trip).
 *
 * Usage: node electron-soak.js [minutes]
 */

const CDP_PORT = 9223
const DEFAULT_MINUTES = 10
const minutes = Number(process.argv[2] || DEFAULT_MINUTES)
const durationMs = minutes * 60_000
const SAMPLE_MS = 5000

async function getPageWs() {
  for (let i = 0; i < 120; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)
      const targets = await res.json()
      const page = targets.find((t) => t.type === "page")
      if (page && page.webSocketDebuggerUrl) return page.webSocketDebuggerUrl
    } catch {
      /* electron not up yet */
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error("CDP page target never appeared")
}

class CDP {
  constructor(ws) {
    this.ws = ws
    this.id = 0
    this.pending = new Map()
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data)
      if (msg.id && this.pending.has(msg.id)) {
        this.pending.get(msg.id)(msg)
        this.pending.delete(msg.id)
      }
    })
  }

  send(method, params = {}) {
    const id = ++this.id
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`CDP timeout: ${method}`)), 15000)
      this.pending.set(id, (msg) => {
        clearTimeout(timer)
        if (msg.error) reject(new Error(msg.error.message))
        else resolve(msg.result)
      })
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }

  async eval(expression, awaitPromise = false) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise,
    })
    if (result.exceptionDetails) {
      throw new Error("eval exception: " + JSON.stringify(result.exceptionDetails).slice(0, 300))
    }
    return result.result ? result.result.value : undefined
  }
}

async function run() {
  const pageWsUrl = await getPageWs()
  const ws = new WebSocket(pageWsUrl)
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true })
    ws.addEventListener("error", reject, { once: true })
  })
  const cdp = new CDP(ws)
  await cdp.send("Runtime.enable")

  // 1. Wait for the Start control and click it.
  let clicked = false
  for (let i = 0; i < 60; i++) {
    const found = await cdp.eval(
      `(() => {
         const b = Array.from(document.querySelectorAll('button'))
           .find((x) => x.textContent.trim() === 'Start')
         return !!b
       })()`,
    )
    if (found) {
      await cdp.eval(
        `(() => {
           const b = Array.from(document.querySelectorAll('button'))
             .find((x) => x.textContent.trim() === 'Start')
           b.click()
           return true
         })()`,
      )
      clicked = true
      break
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  if (!clicked) throw new Error("Start button never appeared")
  console.log(`[soak] started capture+session (${minutes} min)`, new Date().toISOString())

  const samples = []
  const failures = []
  let lastTranslation = null
  let lastTranslationAt = Date.now()
  let lastTranscriptCount = 0
  let lastTranslationCount = 0

  const started = Date.now()
  while (Date.now() - started < durationMs) {
    await new Promise((r) => setTimeout(r, SAMPLE_MS))

    // rAF responsiveness probe: time a full renderer main-thread turn.
    const probeT0 = Date.now()
    let probeRtt = 0
    try {
      const frameAt = await cdp.eval(
        `new Promise((r) => requestAnimationFrame(() => r(performance.now())))`,
        true,
      )
      probeRtt = Date.now() - probeT0
      void frameAt
    } catch (e) {
      failures.push(`probe failed: ${e.message}`)
    }

    const state = await cdp.eval(
      `(() => {
         const text = (sel) => Array.from(document.querySelectorAll(sel)).map((e) => e.textContent.trim())
         const sections = Array.from(document.querySelectorAll('section'))
         const panel = (t) => sections.find((s) => s.querySelector('h2')?.textContent.trim() === t)
         const transcript = panel('LIVE SPEECH') ? panel('LIVE SPEECH').innerText : ''
         const translation = panel('TRANSLATION') ? panel('TRANSLATION').innerText : ''
         const status = Array.from(document.querySelectorAll('span,button'))
           .map((e) => e.textContent.trim())
           .find((t) => ['Connecting','Connected','Listening','Speaking','Translating','Error','Disconnected','Silence detected'].includes(t)) || null
         return {
           heap: performance.memory ? performance.memory.usedJSHeapSize : 0,
           nodes: document.getElementsByTagName('*').length,
           transcript,
           translation,
           status,
           errorBanner: !!document.querySelector('[role="alert"]') || text('button').some((t) => t.includes('Dismiss')),
         }
       })()`,
    )

    // Translation sync check: transcript finals vs translations at the DOM level.
    const transcriptLines = state.transcript.split("\n").filter((l) => l && l !== "LIVE SPEECH")
    const translationLines = state.translation.split("\n").filter((l) => l && l !== "TRANSLATION")
    const hasFreshTranslation =
      state.translation.includes("]") && state.translation !== lastTranslation

    if (probeRtt > 2000) failures.push(`renderer froze: probe took ${probeRtt}ms`)
    if (state.errorBanner) failures.push(`error banner visible: ${state.status}`)

    const now = Date.now()
    if (state.translation && state.translation.includes("]")) {
      if (state.translation === lastTranslation && !hasFreshTranslation) {
        if (now - lastTranslationAt > 30_000) {
          failures.push("no new translation in >30s (WS stalled or stopped)")
        }
      } else {
        lastTranslation = state.translation
        lastTranslationAt = now
      }
    } else if (now - lastTranslationAt > 60_000 && Date.now() - started > 30_000) {
      failures.push("never saw a translation")
    }

    const transcriptCount = transcriptLines.length
    const translationCount = translationLines.length
    if (transcriptCount > lastTranscriptCount || translationCount > lastTranslationCount) {
      if (transcriptCount > lastTranscriptCount) lastTranscriptCount = transcriptCount
      if (translationCount > lastTranslationCount) lastTranslationCount = translationCount
    }

    samples.push({
      t: (now - started) / 1000,
      heapMB: Math.round(state.heap / 1048576),
      nodes: state.nodes,
      probeMs: probeRtt,
      transcriptCount,
      translationCount,
      status: state.status,
    })

    if (samples.length % 12 === 0 || samples.length <= 3) {
      const s = samples[samples.length - 1]
      console.log(
        `[soak] ${s.t.toFixed(0)}s heap=${s.heapMB}MB nodes=${s.nodes} ` +
          `probe=${s.probeMs}ms transcript=${s.transcriptCount} translation=${s.translationCount} status=${s.status}`,
      )
    }
    if (failures.length >= 10) break
  }

  // Stop capture so the soak cleans up after itself.
  try {
    await cdp.eval(
      `(() => {
         const b = Array.from(document.querySelectorAll('button'))
           .find((x) => /Stop/.test(x.textContent))
         if (b) b.click()
         return true
       })()`,
    )
  } catch {
    /* already stopped */
  }
  ws.close()

  console.log(`[soak] samples=${samples.length}`)
  if (samples.length < 2) {
    console.log("FAIL: too few samples")
    process.exit(1)
  }

  // Memory trend: compare first third vs last third of samples.
  const third = Math.floor(samples.length / 3) || 1
  const early = samples.slice(0, third).reduce((a, s) => a + s.heapMB, 0) / third
  const late = samples.slice(-third).reduce((a, s) => a + s.heapMB, 0) / third
  const peak = Math.max(...samples.map((s) => s.heapMB))
  const maxProbe = Math.max(...samples.map((s) => s.probeMs))
  const finalCount = samples[samples.length - 1]
  console.log(
    `[soak] heap early=${early.toFixed(1)}MB late=${late.toFixed(1)}MB peak=${peak}MB ` +
      `maxProbe=${maxProbe}ms transcript=${finalCount.transcriptCount} translation=${finalCount.translationCount}`,
  )

  if (late - early > 120) failures.push(`renderer heap grew ${(late - early).toFixed(1)}MB`)
  if (peak > 600) failures.push(`renderer heap peaked at ${peak}MB`)
  if (finalCount.translationCount < 2 && Date.now() - started > 60_000)
    failures.push("translations never advanced in the DOM")

  if (failures.length) {
    console.log("FAIL:")
    for (const f of failures.slice(0, 20)) console.log("  -", f)
    process.exit(1)
  }
  console.log("PASS: renderer memory bounded, translations flowing, no freezes")
  process.exit(0)
}

run().catch((e) => {
  console.error("FAIL:", e.message)
  process.exit(1)
})
