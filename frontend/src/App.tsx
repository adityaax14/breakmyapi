import { useEffect, useState } from "react";

import { getMe, getToken, logOut, onLoggedOut, type Scan, type User } from "./api";
import History from "./components/History";
import Library from "./components/Library";
import Login from "./components/Login";
import RequestLog from "./components/RequestLog";
import ScanForm from "./components/ScanForm";
import ScanProgress from "./components/ScanProgress";

type Tab = "scan" | "history" | "library";

export default function App() {
  const [tab, setTab] = useState<Tab>("scan");
  const [scan, setScan] = useState<Scan | null>(null);
  const [user, setUser] = useState<User | null | "checking">(getToken() ? "checking" : null);

  useEffect(() => {
    if (getToken()) getMe().then(setUser).catch(() => setUser(null));
    return onLoggedOut(() => {
      setUser(null);
      setScan(null);
    });
  }, []);

  async function handleLogOut() {
    await logOut().catch(() => {});
    setUser(null);
    setScan(null);
  }

  const loggedIn = user !== null && user !== "checking";

  function go(next: Tab) {
    setTab(next);
    if (next !== "scan") setScan(null);
  }

  const tabClass = (name: Tab) =>
    [
      "relative rounded-lg px-3.5 py-1.5 text-sm font-medium transition",
      tab === name ? "text-white" : "text-zinc-500 hover:text-zinc-200",
    ].join(" ");

  return (
    <div className="mx-auto max-w-6xl px-5 pb-24 pt-8">
      {/* ---- top bar ---- */}
      <header className="flex flex-wrap items-center justify-between gap-4">
        <button onClick={() => go("scan")} className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white text-[15px] font-black text-black">
            B
          </span>
          <span className="text-[15px] font-semibold tracking-tight">BreakMyAPI</span>
        </button>

        <div className="flex items-center gap-3">
          <nav className="flex items-center gap-0.5 rounded-xl border border-white/10 bg-white/[0.02] p-1 backdrop-blur">
            <button className={tabClass("scan")} onClick={() => go("scan")}>
              Scan
            </button>
            <button className={tabClass("history")} onClick={() => go("history")}>
              History
            </button>
            <button className={tabClass("library")} onClick={() => go("library")}>
              Library
            </button>
          </nav>
          {loggedIn && (
            <div className="flex items-center gap-2">
              <span className="hidden max-w-[11rem] truncate text-xs text-zinc-500 sm:block">{user.email}</span>
              <button onClick={handleLogOut} className="btn btn-ghost px-3 py-1.5 text-xs">
                Log out
              </button>
            </div>
          )}
        </div>
      </header>

      {/* ---- hero ---- */}
      <section className="mt-16 mb-10 text-center">
        <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs text-zinc-400">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
          Autonomous API security agent
        </div>
        <h1 className="mx-auto max-w-3xl text-balance text-4xl font-bold leading-[1.05] tracking-tight sm:text-5xl">
          Find the bugs in your API
          <br className="hidden sm:block" /> before your interviewer does.
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-balance text-[15px] leading-relaxed text-zinc-400">
          Submit an OpenAPI spec and an agent probes your running API for the OWASP API Top&nbsp;10 —
          then writes a cited report with fixes for your framework.
        </p>
      </section>

      {/* ---- workspace ---- */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_21rem]">
        <main className="card p-6 sm:p-7">
          {tab === "library" ? (
            <Library />
          ) : user === "checking" ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-zinc-500">
              <span className="h-2 w-2 animate-pulse rounded-full bg-zinc-500" />
              Checking your session…
            </div>
          ) : user === null ? (
            <Login onLoggedIn={setUser} />
          ) : tab === "history" ? (
            <History
              onOpen={(picked) => {
                setScan(picked);
                setTab("scan");
              }}
            />
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
