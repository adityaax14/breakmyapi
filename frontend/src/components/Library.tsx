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
        setHits(answer.sources);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }

  const modeClass = (name: Mode) =>
    ["rounded-lg px-3 py-1.5 text-sm font-medium transition", mode === name ? "text-white" : "text-zinc-500 hover:text-zinc-200"].join(" ");

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="eyebrow">OWASP library</div>
          <h2 className="mt-1 text-lg font-semibold tracking-tight">
            {mode === "search" ? "Search the guidance" : "Ask the guidance"}
          </h2>
          <p className="mt-1 text-sm text-zinc-500">
            {mode === "search"
              ? "Semantic search across 233 sections of OWASP guidance."
              : "The best sections are retrieved, then the AI answers from them — with citations."}
          </p>
        </div>
        <div className="flex gap-0.5 rounded-xl border border-white/10 bg-white/[0.02] p-1">
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
          className="field"
          placeholder="e.g. how should an API validate JWT tokens?"
        />
        <div className="flex flex-wrap gap-2">
          <div className="relative min-w-0 flex-1">
            <select value={check} onChange={(e) => setCheck(e.target.value)} className="field appearance-none pr-10">
              <option value="" className="bg-zinc-900">
                All topics
              </option>
              {checks.map((c) => (
                <option key={c.id} value={c.id} className="bg-zinc-900">
                  Only: {c.name}
                </option>
              ))}
            </select>
            <span className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-zinc-500">▾</span>
          </div>
          <button type="submit" disabled={busy || question.trim().length < 3} className="btn btn-primary px-6">
            {busy ? (mode === "ask" ? "Thinking…" : "Searching…") : mode === "ask" ? "Ask" : "Search"}
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setQuestion(example)}
              className="rounded-lg border border-white/10 px-2.5 py-1 text-xs text-zinc-500 transition hover:border-white/25 hover:text-zinc-200"
            >
              {example}
            </button>
          ))}
        </div>
      </form>

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/[0.07] px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {result && (
        <div className="card-inset p-5">
          <div className="eyebrow">Answer</div>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-zinc-100">{result.answer}</p>
          <div className="mt-3 border-t border-white/5 pt-3 text-xs text-zinc-600">
            Cites {result.cited.length ? result.cited.map((n) => `[${n}]`).join(" ") : "no sources"} · {result.tokens}{" "}
            tokens · written only from the sources below
          </div>
        </div>
      )}

      {hits && hits.length === 0 && <div className="text-sm text-zinc-500">No sections found.</div>}

      {hits && hits.length > 0 && (
        <div className="space-y-3">
          {result && <div className="eyebrow">Sources</div>}
          <ol className="space-y-3">
            {hits.map((hit, i) => (
              <li key={hit.chunk_id} className="card p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="mono text-xs text-zinc-600">
                      {result ? `[${i + 1}]` : `#${i + 1}`} · {hit.chunk_id}
                      {result?.cited.includes(i + 1) && (
                        <span className="ml-2 rounded bg-emerald-500/10 px-1.5 py-0.5 text-emerald-400">cited</span>
                      )}
                    </div>
                    <div className="mt-1 text-sm font-medium text-zinc-100">{hit.heading}</div>
                  </div>
                  <span className="mono shrink-0 rounded-full border border-white/10 bg-white/[0.03] px-2 py-0.5 text-xs text-zinc-400">
                    {hit.score.toFixed(2)}
                  </span>
                </div>
                <p className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-zinc-400">
                  {hit.text}
                </p>
                <a
                  href={hit.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-block text-xs text-zinc-400 underline-offset-2 hover:text-zinc-200 hover:underline"
                >
                  Source: OWASP ↗
                </a>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
