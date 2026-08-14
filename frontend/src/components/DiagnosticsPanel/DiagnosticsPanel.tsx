import type { ConnectionState } from "../../types"
import type { VADStatus } from "../../providers/vad/types"

export interface DiagnosticsPanelProps {
  sampleRate: number | null
  chunkSizeBytes: number
  chunksPerSecond: number
  bytesSent: number
  bytesReceived: number
  connectionState: ConnectionState
  vadStatus: VADStatus
  vadReady: boolean
  vadError: string | null
  vadProbability: number | null
  vadSilenceThresholdMs: number
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

interface RowProps {
  label: string
  value: string
}

function Row({ label, value }: RowProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
        {label}
      </dt>
      <dd className="text-sm text-slate-700">{value}</dd>
    </div>
  )
}

function vadModelLabel(ready: boolean, error: string | null, status: VADStatus): string {
  if (error) return `error (${status})`
  if (!ready) return "loading…"
  return status
}

export function DiagnosticsPanel({
  sampleRate,
  chunkSizeBytes,
  chunksPerSecond,
  bytesSent,
  bytesReceived,
  connectionState,
  vadStatus,
  vadReady,
  vadError,
  vadProbability,
  vadSilenceThresholdMs,
}: DiagnosticsPanelProps) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-700">
        Audio diagnostics{" "}
        <span className="font-normal text-slate-400">(development)</span>
      </h2>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 font-mono sm:grid-cols-3">
        <Row
          label="Sample rate"
          value={sampleRate !== null ? `${sampleRate.toLocaleString()} Hz` : "—"}
        />
        <Row label="Chunk size" value={`${chunkSizeBytes} B`} />
        <Row label="Chunks / sec" value={chunksPerSecond.toFixed(0)} />
        <Row label="Bytes sent" value={formatBytes(bytesSent)} />
        <Row label="Bytes received (server)" value={formatBytes(bytesReceived)} />
        <Row label="WebSocket state" value={connectionState} />
        <Row label="VAD model" value={vadModelLabel(vadReady, vadError, vadStatus)} />
        <Row
          label="VAD probability"
          value={vadProbability !== null ? vadProbability.toFixed(3) : "—"}
        />
        <Row label="VAD silence threshold" value={`${vadSilenceThresholdMs} ms`} />
      </dl>
    </section>
  )
}
