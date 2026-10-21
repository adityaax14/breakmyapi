import { useEffect, useState } from "react";

import {
  ApiError,
  askLibrary,
  getChecks,
  searchLibrary,
  type AskResult,
  type CheckInfo,
  type LibraryHit,
} from "../api";

type Mode = "search" | "ask";

const EXAMPLES = [
  "how do I stop clients setting fields they should not change?",
  "should the API return the whole database object?",
  "fix mass assignment in Django",
];

export default function Library() {
  const [checks, setChecks] = useState<CheckInfo[]>([]);
  const [question, setQuestion] = useState(EXAMPLES[0]);
  const [check, setCheck] = useState<string>("");
  const [mode, setMode] = useState<Mode>("search");
  const [hits, setHits] = useState<LibraryHit[] | null>(null);
  const [result, setResult] = useState<AskResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load the list of checks once, for the filter dropdown.
  useEffect(() => {
    getChecks().then(setChecks).catch(() => setChecks([]));
  }, []);

  function switchMode(next: Mode) {
    setMode(next);
    setHits(null);
    setResult(null);
    setError(null);
  }

  async function run(e?: React.FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      if (mode === "search") {
        setHits(await searchLibrary(question, check || null));
      } else {
        const answer = await askLibrary(question, check || null);
        setResult(answer);
        setHits(answer.sources); // show the sources the answer was written from
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }

  const modeClass = (name: Mode) =>
    [
      "rounded-lg px-3 py-1.5 text-sm font-medium transition",
      mode === name ? "bg-slate-800 text-white" : "text-slate-400 hover:text-white",
    ].join(" ");

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">OWASP library</h2>
          <p className="mt-1 text-sm text-slate-400">
            {mode === "search"
              ? "Search 233 sections of OWASP guidance by meaning."
              : "Ask a question: the best sections are found, then the AI answers from them, with citations."}
          </p>
        </div>
        <div className="flex gap-1 rounded-xl border border-slate-800 bg-slate-900/60 p-1">
          <button type="button" className={modeClass("search")} onClick={() => switchMode("search")}>
            Search
          </button>
          <button type="button" className={modeClass("ask")} onClick={() => switchMode("ask")}>
            Ask
          </button>
        </div>
      </div>

      <form onSubmit={run} className="space-y-3">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          className="w-full rounded-xl border border-slate-700 bg-slate-900/60 px-4 py-2.5 text-sm outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-400/30"
          placeholder="Ask a question, for example: how should an API validate JWT tokens?"
        />
        <div className="flex flex-wrap gap-2">
          <select
            value={check}
            onChange={(e) => setCheck(e.target.value)}
            className="min-w-0 flex-1 rounded-xl border border-slate-700 bg-slate-900/60 px-3 py-2.5 text-sm outline-none focus:border-indigo-400"
          >
            <option value="">All topics</option>
            {checks.map((c) => (
              <option key={c.id} value={c.id}>
                Only: {c.name}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={busy || question.trim().length < 3}
            className="rounded-xl bg-indigo-500 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-400 disabled:opacity-40"
          >
            {busy ? (mode === "ask" ? "Thinking…" : "Searching…") : mode === "ask" ? "Ask" : "Search"}
          </button>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setQuestion(example)}
              className="rounded-lg border border-slate-800 px-2.5 py-1 text-slate-400 transition hover:border-indigo-400 hover:text-white"
            >
              {example}
            </button>
          ))}
        </div>
      </form>

      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{error}</div>
      )}

      {result && (
        <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/5 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-indigo-300">Answer</div>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-100">{result.answer}</p>
          <div className="mt-3 text-xs text-slate-500">
            Cites {result.cited.length ? result.cited.map((n) => `[${n}]`).join(" ") : "no sources"} ·{" "}
            {result.tokens} tokens · written only from the sources below
          </div>
        </div>
      )}

      {hits && hits.length === 0 && <div className="text-sm text-slate-500">No sections found.</div>}

      {hits && hits.length > 0 && (
        <ol className="space-y-3">
          {result && <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Sources</div>}
          {hits.map((hit, i) => (
            <li key={hit.chunk_id} className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs text-slate-500">
                    {result ? `[${i + 1}]` : `#${i + 1}`} · {hit.chunk_id}
                    {result?.cited.includes(i + 1) && (
                      <span className="ml-2 rounded bg-emerald-500/15 px-1.5 py-0.5 text-emerald-300">cited</span>
                    )}
                  </div>
                  <div className="mt-0.5 text-sm font-medium text-slate-100">{hit.heading}</div>
                </div>
                <span className="shrink-0 rounded-full bg-indigo-500/15 px-2 py-0.5 font-mono text-xs text-indigo-200">
                  {hit.score.toFixed(2)}
                </span>
              </div>
              <p className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-slate-300">
                {hit.text}
              </p>
              <a
                href={hit.url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-block text-xs text-indigo-300 hover:text-indigo-200"
              >
                Source: OWASP ↗
              </a>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
