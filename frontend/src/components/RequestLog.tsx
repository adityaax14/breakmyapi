import { useSyncExternalStore } from "react";

import { getLog, subscribeLog } from "../api";

// Shows every HTTP request this page has sent to the backend, newest first.
export default function RequestLog() {
  const entries = useSyncExternalStore(subscribeLog, getLog);

  return (
    <div className="card sticky top-8 p-5">
      <div className="flex items-center gap-2">
        <span className="h-1.5 w-1.5 rounded-full bg-zinc-600" />
        <h2 className="eyebrow">Network log</h2>
      </div>
      <p className="mt-1.5 text-xs text-zinc-600">Every request this page sends to the backend.</p>

      <div className="mono mt-4 max-h-[26rem] space-y-1 overflow-y-auto text-xs">
        {entries.length === 0 && <div className="text-zinc-700">No requests yet.</div>}
        {entries.map((e) => {
          const ok = e.status === "stream" || (typeof e.status === "number" && e.status < 400);
          return (
            <div
              key={e.id}
              className="flex items-center gap-2 rounded-lg border border-white/[0.04] bg-black/20 px-2.5 py-1.5"
            >
              <span className="text-zinc-600">{e.time.slice(0, 8)}</span>
              <span className={e.method === "POST" ? "font-semibold text-amber-400/80" : "font-semibold text-sky-400/80"}>
                {e.method}
              </span>
              <span className="min-w-0 flex-1 truncate text-zinc-400">{e.path}</span>
              <span className={ok ? "text-emerald-400/80" : "text-rose-400/80"}>{e.status}</span>
              <span className="text-zinc-700">{e.ms}ms</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
