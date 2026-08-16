import type { ConnectionState, LatencyReport } from "../../types"
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
  /** Latest per-utterance latency report (dev-only). */
  latency: LatencyReport | null
  /** Rolling per-utterance latency reports (dev-only). */
  latencyHistory: LatencyReport[]
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

function ms(value: number | null | undefined): string {
  return value != null ? `${Math.round(value)} ms` : "—"
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
  latency,
  latencyHistory,
}: DiagnosticsPanelProps) {
  const { asr_partial_ms, asr_final_ms, translation_ms, end_to_end_ms } = latency ?? {}
  const ui = latency?.final_to_translation_ms ?? latency?.ui_ms ?? null
  const speechToTranslation = latency?.speech_to_translation_ms ?? null
  const refinement = latency?.refinement_ms ?? null
  const network = latency?.network_ms ?? null

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-700">
        Performance &amp; latency{" "}
        <span className="font-normal text-slate-400">(development only)</span>
      </h2>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 font-mono sm:grid-cols-3">
        <Row
          label="Speech → translation"
          value={speechToTranslation != null ? ms(speechToTranslation) : "—"}
        />
        <Row label="ASR final → UI" value={ms(ui)} />
        <Row label="Server end-to-end" value={ms(end_to_end_ms)} />
        <Row label="ASR final (T4-T2)" value={ms(asr_final_ms)} />
        <Row label="ASR partial (T3-T2)" value={ms(asr_partial_ms)} />
        <Row label="Translation (T6-T5)" value={ms(translation_ms)} />
        <Row label="LLM refinement" value={ms(refinement)} />
        <Row label="Network (half RTT)" value={ms(network)} />
        <Row label="Sample rate" value={sampleRate !== null ? `${sampleRate.toLocaleString()} Hz` : "—"} />
        <Row label="Chunk size" value={`${chunkSizeBytes} B`} />
        <Row label="Chunks / sec" value={chunksPerSecond.toFixed(0)} />
        <Row label="Bytes sent" value={formatBytes(bytesSent)} />
        <Row label="Bytes received (server)" value={formatBytes(bytesReceived)} />
        <Row label="WebSocket state" value={connectionState} />
        <Row label="VAD model" value={vadModelLabel(vadReady, vadError, vadStatus)} />
        <Row label="VAD probability" value={vadProbability !== null ? vadProbability.toFixed(3) : "—"} />
        <Row label="VAD silence threshold" value={`${vadSilenceThresholdMs} ms`} />
      </dl>

      {latencyHistory.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs font-medium uppercase tracking-wide text-slate-400">
            Recent utterances
          </h3>
          <ul className="mt-2 divide-y divide-slate-100 font-mono text-xs text-slate-600">
            {latencyHistory.slice(0, 5).map((report) => (
              <li key={report.segment_id} className="flex items-center justify-between py-1.5">
                <span className="truncate text-slate-400">{report.segment_id}</span>
                <span className="shrink-0">
                  {ms(report.speech_to_translation_ms ?? report.end_to_end_ms)} → translate{" "}
                  {ms(report.translation_ms)}
                  {report.refinement_ms != null ? ` · refine ${ms(report.refinement_ms)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
