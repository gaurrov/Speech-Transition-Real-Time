import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    conditions: [
      // Pick the extern-wasm onnxruntime-web build: the loader and its .wasm
      // are hosted in public/vendor/onnx/ and loaded at runtime via
      // ort.env.wasm.wasmPaths, so the 13 MB wasm must not be bundled/emitted.
      "onnxruntime-web-use-extern-wasm",
    ],
  },
  build: {
    // AudioWorklet.addModule needs a real same-origin JS module URL; an
    // inlined data: URL is rejected. Emit every asset as a file instead.
    assetsInlineLimit: 0,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
})
