// Runtime configuration for the Live Translator renderer.
//
// This file is loaded by index.html BEFORE the app bundle so the WebSocket
// client can pick up the deployed backend URL without a rebuild:
//
//   - Docker web deployment: the nginx container regenerates this file at
//     startup from the BACKEND_HOST / BACKEND_USE_TLS environment variables.
//   - Electron (file://): edit the values below directly in this file (it
//     ships next to index.html in the built dist folder).
//
// backendHost: host[:port] of the FastAPI backend. Leave "" (empty) to connect
// to the same origin that served this page (recommended for the Docker
// nginx deployment). For a separate API domain use e.g. "api.example.com".
// useTls: true -> wss:// (production), false -> ws:// (local dev).
window.TRANSLATOR_CONFIG = {
  backendHost: "",
  useTls: false,
}
