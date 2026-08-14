/* AudioWorklet processor that converts raw Float32 microphone frames into
 * small 16 kHz mono PCM16 chunks and posts them to the main thread.
 *
 * It runs off the main thread on the AudioContext's render thread. It:
 *   - resamples the incoming stream to the ASR target rate (16 kHz) with a
 *     cheap linear interpolator,
 *   - buffers the resampled frames into fixed-size chunks (no extra latency
 *     beyond one chunk duration),
 *   - converts Float32 -> little-endian Int16 and posts the ArrayBuffer
 *     (transferred, so zero copies),
 *   - does a basic RMS-based activity check to drive the UI's
 *     Listening / Speaking indicator.
 *
 * This file must stay self-contained (no imports) and plain JavaScript:
 * AudioWorklet.addModule loads it directly, so it cannot go through the
 * bundler's module pipeline.
 */
"use strict"

class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.queue = []
    this.frac0 = 0
    this.ratio = 1
    this.chunkSamples = 1600
    this.speechThreshold = 0.012
    this.hangoverSeconds = 0.35
    this.speaking = false
    this.hangoverRemaining = 0
    this.vadQueue = []
    this.vadEnabled = false
    this.vadWindowSize = 512

    this.port.onmessage = (event) => {
      const message = event.data
      if (!message || message.type !== "configure") return
      this.applyConfig(message)
    }
  }

  process(inputs, _outputs) {
    const input = inputs[0] && inputs[0][0]
    if (input && input.length > 0) {
      this.pushResampled(input)
      this.updateActivity(input)
    }

    if (this.queue.length >= this.chunkSamples) {
      const samples = this.queue.splice(0, this.chunkSamples)
      const pcm = new Int16Array(samples.length)
      for (let i = 0; i < samples.length; i += 1) {
        let value = samples[i]
        if (value > 1) value = 1
        else if (value < -1) value = -1
        pcm[i] = value < 0 ? value * 0x8000 : value * 0x7fff
      }
      this.port.postMessage({ type: "audio", buffer: pcm.buffer }, [pcm.buffer])
    }

    if (this.vadEnabled && this.vadQueue.length >= this.vadWindowSize) {
      const samples = this.vadQueue.splice(0, this.vadWindowSize)
      const float = new Float32Array(samples)
      this.port.postMessage({ type: "vad", samples: float }, [float.buffer])
    }

    return true
  }

  applyConfig(message) {
    if (typeof message.chunkSamples === "number") {
      this.chunkSamples = message.chunkSamples
    }
    if (typeof message.speechThreshold === "number") {
      this.speechThreshold = message.speechThreshold
    }
    if (typeof message.hangoverMs === "number") {
      this.hangoverSeconds = message.hangoverMs / 1000
    }
    if (typeof message.outputSampleRate === "number") {
      this.ratio = sampleRate / message.outputSampleRate
    }
    if (typeof message.vadEnabled === "boolean") {
      this.vadEnabled = message.vadEnabled
    }
    if (typeof message.vadWindowSize === "number") {
      this.vadWindowSize = message.vadWindowSize
    }
    this.frac0 = 0
    this.queue.length = 0
    this.vadQueue.length = 0
  }

  pushResampled(input) {
    const last = input.length - 1
    if (last < 0) return
    let position = this.frac0
    while (position <= last) {
      const i0 = Math.floor(position)
      const i1 = i0 < last ? i0 + 1 : last
      const fraction = position - i0
      const value = input[i0] * (1 - fraction) + input[i1] * fraction
      this.queue.push(value)
      if (this.vadEnabled) {
        this.vadQueue.push(value)
      }
      position += this.ratio
    }
    this.frac0 = position - last
  }

  updateActivity(input) {
    let sumOfSquares = 0
    for (let i = 0; i < input.length; i += 1) {
      const value = input[i]
      sumOfSquares += value * value
    }
    const rms = Math.sqrt(sumOfSquares / input.length)
    const quantumSeconds = input.length / sampleRate

    if (rms >= this.speechThreshold) {
      this.hangoverRemaining = this.hangoverSeconds
      if (!this.speaking) {
        this.speaking = true
        this.port.postMessage({ type: "activity", active: true })
      }
    } else if (this.speaking) {
      this.hangoverRemaining -= quantumSeconds
      if (this.hangoverRemaining <= 0) {
        this.speaking = false
        this.port.postMessage({ type: "activity", active: false })
      }
    }
  }
}

registerProcessor("pcm-capture-processor", PcmCaptureProcessor)
