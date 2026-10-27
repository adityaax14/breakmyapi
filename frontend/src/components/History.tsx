import { useEffect, useState } from "react";

import { ApiError, listScans, PAGE_SIZE, type Scan, type ScanPage } from "../api";

const STATUS_STYLE: Record<string, string> = {
  completed: "border-emerald-400/30 bg-emerald-500/10 text-emerald-300",
  failed: "border-rose-400/30 bg-rose-500/10 text-rose-300",
  running: "border-white/20 bg-white/[0.05] text-zinc-200",
  queued: "border-white/10 bg-white/[0.02] text-zinc-400",
  waiting_approval: "border-amber-400/30 bg-amber-500/10 text-amber-300",
  cancelled: "border-white/10 bg-white/[0.02] text-zinc-500",
};

export default function History({ onOpen }: { onOpen: (scan: Scan) => void }) {
  const [page, setPage] = useState(0);
  const [data, setData] = useState<ScanPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    listScans(page)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load scans."));
  }, [page]);

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const first = page * PAGE_SIZE + 1;
  const last = data ? page * PAGE_SIZE + data.items.length : 0;

  return (
    <div className="space-y-5">
      <div>
        <div className="eyebrow">History</div>
        <h2 className="mt-1 text-lg font-semibold tracking-tight">Your scans</h2>
        <p className="mt-1 text-sm text-zinc-500">Newest first. Open one to replay its activity and report.</p>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/[0.07] px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {data && data.items.length === 0 && (
        <div className="rounded-xl border border-dashed border-white/10 px-4 py-10 text-center text-sm text-zinc-600">
          No scans yet. Start one from the Scan tab.
        </div>
      )}

      {data && data.items.length > 0 && (
        <ul className="divide-y divide-white/5 overflow-hidden rounded-xl border border-white/10">
          {data.items.map((scan) => (
            <li key={scan.id}>
              <button
                onClick={() => onOpen(scan)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-white/[0.03]"
              >
                <span
                  className={`w-28 shrink-0 rounded-full border px-2 py-0.5 text-center text-[11px] font-medium ${
                    STATUS_STYLE[scan.status] ?? STATUS_STYLE.queued
                  }`}
                >
                  {scan.status.replace("_", " ")}
                </span>
                <span className="mono min-w-0 flex-1 truncate text-xs text-zinc-300">{scan.target_url}</span>
                <span className="mono hidden shrink-0 text-xs text-zinc-600 sm:block">{scan.id.slice(0, 8)}</span>
                <span className="hidden shrink-0 text-xs text-zinc-600 md:block">
                  {new Date(scan.created_at).toLocaleString()}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {data && data.total > 0 && (
        <div className="flex items-center justify-between text-sm text-zinc-500">
          <span>
            {first}–{last} of {data.total}
          </span>
          <div className="flex gap-2">
            <button disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="btn btn-ghost px-3 py-1.5 text-xs">
              Newer
            </button>
            <button
              disabled={page + 1 >= pages}
              onClick={() => setPage((p) => p + 1)}
              className="btn btn-ghost px-3 py-1.5 text-xs"
            >
              Older
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
