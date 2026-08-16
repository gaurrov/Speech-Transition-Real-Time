/**
 * Runtime-configurable server endpoint.
 *
 * The deployed backend URL must be changeable WITHOUT rebuilding the frontend.
 * `config.js` (loaded by index.html before the app bundle) sets
 * `window.TRANSLATOR_CONFIG`, which the WebSocket client reads at runtime:
 *
 *   - Web deployment: the nginx container generates config.js from
 *     BACKEND_HOST / BACKEND_USE_TLS at startup. Leave BACKEND_HOST empty to
 *     connect same-origin (wss://<wherever-the-page-was-loaded>).
 *   - Electron (file://): edit `config.js` next to index.html in the built
 *     dist folder and point it at your deployed server (e.g. api.example.com
 *     with useTls true).
 *
 * Build-time fallbacks (VITE_BACKEND_HOST / VITE_BACKEND_USE_TLS) still apply
 * when no runtime config is present.
 */

export interface TranslatorRuntimeConfig {
  backendHost?: string
  useTls?: boolean
}

declare global {
  interface Window {
    TRANSLATOR_CONFIG?: TranslatorRuntimeConfig
  }
}
