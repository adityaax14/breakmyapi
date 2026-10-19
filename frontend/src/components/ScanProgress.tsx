import { useEffect, useState } from "react";

import { ApiError, getScan, isFinished, type Scan, type ScanStatus } from "../api";

const STEPS: { key: ScanStatus; label: string; hint: string }[] = [
  { key: "queued", label: "Queued", hint: "Saved in the database, waiting for the runner" },
  { key: "running", label: "Running", hint: "The runner is working on it" },
  { key: "completed", label: "Completed", hint: "Done" },
];

function stepIndex(status: ScanStatus) {
  if (status === "failed" || status === "cancelled") return 2;
  return STEPS.findIndex((s) => s.key === status);
}

// Polling: ask the backend for the scan's status every second until it finishes.
function useScan(initial: Scan) {
  const [scan, setScan] = useState(initial);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isFinished(scan.status)) return;
    const timer = setTimeout(async () => {
      try {
        setScan(await getScan(scan.id));
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Lost contact with the API.");
      }
    }, 1000);
    return () => clearTimeout(timer);
  }, [scan]);

  return { scan, error };
}

export default function ScanProgress({ initial, onReset }: { initial: Scan; onReset: () => void }) {
  const { scan, error } = useScan(initial);
  const current = stepIndex(scan.status);
  const failed = scan.status === "failed" || scan.status === "cancelled";
  const done = isFinished(scan.status);

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4 text-sm">
        <div className="text-slate-400">Scan ID</div>
        <div className="mt-0.5 break-all font-mono text-xs text-slate-200">{scan.id}</div>
        <div className="mt-3 text-slate-400">Target</div>
        <div className="mt-0.5 font-mono text-xs text-slate-200">{scan.target_url}</div>
      </div>

      <ol className="space-y-4">
        {STEPS.map((step, i) => {
          const reached = i <= current;
          const active = i === current && !done;
          const isLast = i === STEPS.length - 1;
          const bad = isLast && failed;
          const label = bad ? (scan.status === "failed" ? "Failed" : "Cancelled") : step.label;
          return (
            <li key={step.key} className="flex items-start gap-4">
              <span
                className={[
                  "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs font-bold",
                  bad
                    ? "border-rose-400 bg-rose-500/20 text-rose-200"
                    : reached
                      ? "border-emerald-400 bg-emerald-500/20 text-emerald-200"
                      : "border-slate-700 text-slate-500",
                  active ? "animate-pulse" : "",
                ].join(" ")}
              >
                {bad ? "✕" : reached && !active ? "✓" : i + 1}
              </span>
              <div>
                <div className={reached ? "font-medium text-slate-100" : "font-medium text-slate-500"}>
                  {label}
                </div>
                <div className="text-xs text-slate-500">{step.hint}</div>
              </div>
            </li>
          );
        })}
      </ol>

      {error && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          {error}
        </div>
      )}

      <div className="rounded-xl border border-dashed border-slate-700 px-4 py-5 text-center text-sm text-slate-500">
        Findings will appear here once the agent and the checks are built.
      </div>

      <button
        onClick={onReset}
        className="w-full rounded-xl border border-slate-700 px-4 py-2.5 text-sm text-slate-300 transition hover:border-indigo-400 hover:text-white"
      >
        New scan
      </button>
    </div>
  );
}
