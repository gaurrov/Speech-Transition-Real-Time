import "../types/runtimeConfig"

/**
 * Resolve the backend HTTP base URL at runtime.
 *
 * Precedence:
 *   1. window.TRANSLATOR_CONFIG (config.js, editable without a rebuild).
 *   2. Build-time VITE_BACKEND_HOST / VITE_BACKEND_USE_TLS.
 *   3. Same origin that served the page (the Docker nginx reverse proxy).
 *
 * Returns a string like `""` (same-origin), `http://host`, or `https://host`.
 */
export function resolveBackendBaseUrl(): string {
  const cfg = window.TRANSLATOR_CONFIG
  const runtimeHost = cfg?.backendHost?.trim()
  const runtimeTls = cfg?.useTls
  const buildHost = (import.meta.env.VITE_BACKEND_HOST as string | undefined)?.trim()
  const buildTls = import.meta.env.VITE_BACKEND_USE_TLS === "true"

  const host = runtimeHost || buildHost || ""
  const useTls = runtimeTls ?? buildTls

  if (!host && typeof location !== "undefined" && location.host) {
    return ""
  }
  const scheme = useTls ? "https" : "http"
  return `${scheme}://${host}`
}
