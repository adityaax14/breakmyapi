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
  // No scan yet -> show the form. A scan exists -> show its live progress.
  const [scan, setScan] = useState<Scan | null>(null);
  // "checking" while we ask the server whether a saved token still works.
  const [user, setUser] = useState<User | null | "checking">(getToken() ? "checking" : null);

  useEffect(() => {
    // On start-up: a token saved from last time? Ask the server who it belongs to.
    if (getToken()) getMe().then(setUser).catch(() => setUser(null));
    // Any 401 later (session expired) -> back to the login screen.
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
            <button className={tabClass("history")} onClick={() => setTab("history")}>
              History
            </button>
            <button className={tabClass("library")} onClick={() => setTab("library")}>
              Library
            </button>
            {loggedIn && (
              <>
                <span className="hidden max-w-48 truncate self-center px-2 text-xs text-slate-500 sm:block">
                  {user.email}
                </span>
                <button
                  onClick={handleLogOut}
                  className="rounded-lg px-3 py-1.5 text-sm text-slate-400 transition hover:text-white"
                >
                  Log out
                </button>
              </>
            )}
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
            <Library /> // the OWASP library is public: no login needed
          ) : user === "checking" ? (
            <div className="py-10 text-center text-sm text-slate-500">Checking your login…</div>
          ) : user === null ? (
            <Login onLoggedIn={setUser} />
          ) : tab === "history" ? (
            <History
              onOpen={(picked) => {
                setScan(picked); // open the picked scan ...
                setTab("scan"); // ... on the Scan tab, where its live log replays
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
