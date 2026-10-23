import { useEffect, useState } from "react";

import { ApiError, listScans, PAGE_SIZE, type Scan, type ScanPage } from "../api";

const STATUS_STYLE: Record<string, string> = {
  completed: "border-emerald-400/40 bg-emerald-500/10 text-emerald-200",
  failed: "border-rose-400/40 bg-rose-500/10 text-rose-200",
  running: "border-indigo-400/40 bg-indigo-500/10 text-indigo-200",
  queued: "border-slate-600 bg-slate-800/60 text-slate-300",
};

export default function History({ onOpen }: { onOpen: (scan: Scan) => void }) {
  const [page, setPage] = useState(0);
  const [data, setData] = useState<ScanPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load a page whenever the page number changes.
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
        <h2 className="text-lg font-semibold">Scan history</h2>
        <p className="mt-1 text-sm text-slate-400">Every scan, newest first. Click one to replay its live log.</p>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{error}</div>
      )}

      {data && data.items.length === 0 && <div className="text-sm text-slate-500">No scans yet.</div>}

      {data && data.items.length > 0 && (
        <ul className="divide-y divide-slate-800 overflow-hidden rounded-xl border border-slate-800">
          {data.items.map((scan) => (
            <li key={scan.id}>
              <button
                onClick={() => onOpen(scan)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-slate-900/80"
              >
                <span
                  className={`w-24 shrink-0 rounded-full border px-2 py-0.5 text-center text-xs ${
                    STATUS_STYLE[scan.status] ?? STATUS_STYLE.queued
                  }`}
                >
                  {scan.status}
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-xs text-slate-300">{scan.target_url}</span>
                <span className="shrink-0 font-mono text-xs text-slate-500">{scan.id.slice(0, 8)}</span>
                <span className="hidden shrink-0 text-xs text-slate-500 sm:block">
                  {new Date(scan.created_at).toLocaleString()}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {data && data.total > 0 && (
        <div className="flex items-center justify-between text-sm text-slate-400">
          <span>
            Showing {first}–{last} of {data.total}
          </span>
          <div className="flex gap-2">
            <button
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              className="rounded-lg border border-slate-700 px-3 py-1.5 transition hover:border-indigo-400 disabled:opacity-40"
            >
              Newer
            </button>
            <button
              disabled={page + 1 >= pages}
              onClick={() => setPage((p) => p + 1)}
              className="rounded-lg border border-slate-700 px-3 py-1.5 transition hover:border-indigo-400 disabled:opacity-40"
            >
              Older
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
