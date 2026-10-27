import { useEffect, useRef, useState } from "react";

import { cancelScan, isFinished, streamScan, type Scan, type ScanStatus } from "../api";
import ApprovalCard from "./ApprovalCard";
import ReportView from "./ReportView";

const STEPS = [
  { key: "queued", label: "Queued", hint: "Saved and waiting for a runner" },
  { key: "running", label: "Running", hint: "Reading the spec, retrieving guidance, probing endpoints" },
  { key: "completed", label: "Report", hint: "Findings and fixes" },
] as const;

function stepIndex(status: ScanStatus) {
  if (status === "failed" || status === "cancelled") return 2;
  if (status === "waiting_approval") return 1;
  return STEPS.findIndex((s) => s.key === status);
}

// Live updates: one open connection, and the server pushes each new diary line (SSE).
function useScan(initial: Scan) {
  const [scan, setScan] = useState(initial);
  const [log, setLog] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stop = streamScan(
      initial.id,
      (event) => {
        setLog((lines) => [...lines, event.message]);
        setScan((current) => ({ ...current, status: event.status }));
      },
      (status) => setScan((current) => ({ ...current, status })),
      () => setError("Lost the live connection to the API."),
    );
    return stop;
  }, [initial.id]);

  async function cancel() {
    try {
      setScan(await cancelScan(initial.id));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return { scan, setScan, log, error, cancel };
}

// Colour the [PASS]/[FAIL]/[REVIEW]/[ERROR] tag at the start of an activity line.
const TAG_STYLE: Record<string, string> = {
  PASS: "text-emerald-400",
  FAIL: "text-rose-400",
  REVIEW: "text-amber-400",
  ERROR: "text-zinc-400",
};

function LogLine({ line }: { line: string }) {
  const m = line.match(/^\[(PASS|FAIL|REVIEW|ERROR)\]\s+(.*)$/);
  if (m) {
    return (
      <div className="flex gap-2">
        <span className={`font-semibold ${TAG_STYLE[m[1]]}`}>{m[1]}</span>
        <span className="min-w-0 flex-1 text-zinc-400">{m[2]}</span>
      </div>
    );
  }
  return <div className="text-zinc-500">{line}</div>;
}

export default function ScanProgress({ initial, onReset }: { initial: Scan; onReset: () => void }) {
  const { scan, setScan, log, error, cancel } = useScan(initial);
  const [cancelling, setCancelling] = useState(false);
  const logEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [log.length]);

  const current = stepIndex(scan.status);
  const failed = scan.status === "failed" || scan.status === "cancelled";
  const done = isFinished(scan.status);

  return (
    <div className="space-y-7">
      {/* ---- meta ---- */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow">Target</div>
          <div className="mono mt-1 truncate text-sm text-zinc-200">{scan.target_url}</div>
        </div>
        <div className="min-w-0 text-right">
          <div className="eyebrow">Scan</div>
          <div className="mono mt-1 text-sm text-zinc-500">{scan.id.slice(0, 8)}</div>
        </div>
      </div>

      {/* ---- stepper ---- */}
      <ol className="relative space-y-6 pl-1">
        {STEPS.map((step, i) => {
          const reached = i <= current;
          const active = i === current && !done;
          const isLast = i === STEPS.length - 1;
          const bad = isLast && failed;
          const complete = reached && !active && !bad;
          const label = bad ? (scan.status === "failed" ? "Failed" : "Cancelled") : step.label;

          return (
            <li key={step.key} className="relative flex items-start gap-4">
              {/* connecting rail */}
              {i < STEPS.length - 1 && (
                <span
                  className={`absolute left-[13px] top-7 h-[calc(100%+0.3rem)] w-px ${
                    i < current ? "bg-white/25" : "bg-white/10"
                  }`}
                />
              )}
              <span
                className={[
                  "relative z-10 flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full border text-[11px] font-bold transition",
                  bad
                    ? "border-rose-400/60 bg-rose-500/15 text-rose-300"
                    : complete
                      ? "border-white/80 bg-white text-black"
                      : active
                        ? "border-white/60 text-white"
                        : "border-white/15 text-zinc-600",
                ].join(" ")}
              >
                {active && <span className="absolute inset-0 animate-ping rounded-full border border-white/40" />}
                {bad ? "✕" : complete ? "✓" : i + 1}
              </span>
              <div className="pt-0.5">
                <div className={`text-sm font-semibold ${reached ? "text-zinc-100" : "text-zinc-600"}`}>
                  {label}
                  {active && <span className="ml-2 text-xs font-normal text-zinc-500">in progress…</span>}
                </div>
                <div className="mt-0.5 text-xs text-zinc-500">{step.hint}</div>
              </div>
            </li>
          );
        })}
      </ol>

      {scan.status === "waiting_approval" && (
        <ApprovalCard scanId={scan.id} onAnswered={(updated) => setScan(updated)} />
      )}

      {/* ---- live activity ---- */}
      {log.length > 0 && !done && (
        <div className="card-inset overflow-hidden">
          <div className="flex items-center gap-2 border-b border-white/5 px-4 py-2.5">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
            <span className="eyebrow">Live activity</span>
          </div>
          <div className="mono max-h-56 space-y-1 overflow-y-auto p-4 text-xs">
            {log.map((line, i) => (
              <LogLine key={i} line={line} />
            ))}
            <div ref={logEnd} />
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/[0.07] px-4 py-3 text-sm text-amber-300">
          {error}
        </div>
      )}

      {scan.status === "completed" ? (
        <ReportView scanId={scan.id} />
      ) : (
        !done && (
          <div className="rounded-xl border border-dashed border-white/10 px-4 py-6 text-center text-sm text-zinc-600">
            The report appears here when the scan completes.
          </div>
        )
      )}

      {/* ---- actions ---- */}
      <div className="flex gap-3">
        {!done && (
          <button
            disabled={cancelling}
            onClick={async () => {
              setCancelling(true);
              await cancel();
              setCancelling(false);
            }}
            className="btn btn-danger flex-1"
          >
            {cancelling ? "Cancelling…" : "Cancel scan"}
          </button>
        )}
        <button onClick={onReset} className={`btn ${done ? "btn-primary w-full" : "btn-ghost flex-1"}`}>
          {done ? "New scan →" : "New scan"}
        </button>
      </div>
    </div>
  );
}
