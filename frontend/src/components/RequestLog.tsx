import { useSyncExternalStore } from "react";

import { getLog, subscribeLog } from "../api";

// Shows every HTTP request this page has sent to the backend, newest first.
export default function RequestLog() {
  const entries = useSyncExternalStore(subscribeLog, getLog);

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
      <h2 className="text-sm font-semibold text-slate-200">Network log</h2>
      <p className="mt-1 text-xs text-slate-500">Every request this page sends to the backend.</p>

      <div className="mt-4 max-h-[28rem] space-y-1.5 overflow-y-auto font-mono text-xs">
        {entries.length === 0 && <div className="text-slate-600">No requests yet.</div>}
        {entries.map((e) => {
          const ok = e.status === "stream" || (typeof e.status === "number" && e.status < 400);
          return (
            <div key={e.id} className="flex items-center gap-2 rounded-lg bg-slate-900/60 px-2.5 py-1.5">
              <span className="text-slate-500">{e.time}</span>
              <span className={e.method === "POST" ? "text-amber-300" : "text-sky-300"}>{e.method}</span>
              <span className="min-w-0 flex-1 truncate text-slate-300">{e.path}</span>
              <span className={ok ? "text-emerald-300" : "text-rose-300"}>{e.status}</span>
              <span className="text-slate-600">{e.ms}ms</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
