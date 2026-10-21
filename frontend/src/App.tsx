import { useState } from "react";

import type { Scan } from "./api";
import Library from "./components/Library";
import RequestLog from "./components/RequestLog";
import ScanForm from "./components/ScanForm";
import ScanProgress from "./components/ScanProgress";

type Tab = "scan" | "library";

export default function App() {
  const [tab, setTab] = useState<Tab>("scan");
  // No scan yet -> show the form. A scan exists -> show its live progress.
  const [scan, setScan] = useState<Scan | null>(null);

  const tabClass = (name: Tab) =>
    [
      "rounded-lg px-3 py-1.5 text-sm font-medium transition",
      tab === name ? "bg-slate-800 text-white" : "text-slate-400 hover:text-white",
    ].join(" ");

  return (
    <div className="mx-auto max-w-6xl px-5 py-10">
      <header className="mb-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-500 text-lg font-black text-white">
              B
            </div>
            <span className="text-lg font-semibold tracking-tight">BreakMyAPI</span>
          </div>
          <nav className="flex gap-1 rounded-xl border border-slate-800 bg-slate-900/60 p-1">
            <button className={tabClass("scan")} onClick={() => setTab("scan")}>
              Scan
            </button>
            <button className={tabClass("library")} onClick={() => setTab("library")}>
              Library
            </button>
          </nav>
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
          {tab === "library" ? (
            <Library />
          ) : scan ? (
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
