import { useCallback, useEffect, useRef, useState } from "react"
import { resolveBackendBaseUrl } from "../lib/backendUrl"

export interface BackendHealth {
  translationAvailable: boolean | null
  checked: boolean
  recheck: () => void
}

interface HealthResponse {
  providers?: {
    nllb?: {
      service_reachable?: boolean
      in_process_available?: boolean
    }
  }
}

function isNllbReachable(data: HealthResponse): boolean {
  const nllb = data.providers?.nllb
  if (!nllb) return false
  return nllb.service_reachable === true || nllb.in_process_available === true
}

export function useBackendHealth(): BackendHealth {
  const [translationAvailable, setTranslationAvailable] = useState<boolean | null>(null)
  const [checked, setChecked] = useState(false)
  const mountedRef = useRef(true)

  useEffect(() => {
    return () => {
      mountedRef.current = false
    }
  }, [])

  const recheck = useCallback(() => {
    const base = resolveBackendBaseUrl()
    void fetch(`${base}/health`)
      .then((r) => {
        if (!r.ok) return null
        return r.json() as Promise<HealthResponse>
      })
      .then((data) => {
        if (!mountedRef.current) return
        if (data !== null) {
          setTranslationAvailable(isNllbReachable(data))
        }
        setChecked(true)
      })
      .catch(() => {
        if (!mountedRef.current) return
        setChecked(true)
      })
  }, [])

  useEffect(() => {
    recheck()
  }, [recheck])

  return { translationAvailable, checked, recheck }
}
