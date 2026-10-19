import { useState } from "react";

import type { Scan } from "./api";
import RequestLog from "./components/RequestLog";
import ScanForm from "./components/ScanForm";
import ScanProgress from "./components/ScanProgress";

export default function App() {
  // No scan yet -> show the form. A scan exists -> show its live progress.
  const [scan, setScan] = useState<Scan | null>(null);

  return (
    <div className="mx-auto max-w-6xl px-5 py-10">
      <header className="mb-10">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-500 text-lg font-black text-white">
            B
          </div>
          <span className="text-lg font-semibold tracking-tight">BreakMyAPI</span>
        </div>
        <h1 className="mt-8 max-w-2xl text-3xl font-bold tracking-tight sm:text-4xl">
          Find the bugs in your API before your interviewer does.
        </h1>
        <p className="mt-3 max-w-2xl text-slate-400">
          Submit your OpenAPI spec and an agent tests your running API for common security and
          reliability mistakes.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <main className="rounded-2xl border border-slate-800 bg-slate-900/40 p-6 backdrop-blur">
          {scan ? (
            <ScanProgress key={scan.id} initial={scan} onReset={() => setScan(null)} />
          ) : (
            <ScanForm onCreated={setScan} />
          )}
        </main>
        <aside>
          <RequestLog />
        </aside>
      </div>
    </div>
  );
}
