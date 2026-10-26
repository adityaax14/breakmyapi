import { useRef, useState } from "react";

import { ApiError, createScan, FRAMEWORKS, type Framework, type Scan } from "../api";
import { SAMPLE_SPEC } from "../sampleSpec";

export default function ScanForm({ onCreated }: { onCreated: (scan: Scan) => void }) {
  // In Docker the practice target is reached by its service name, not localhost (see docker-compose.yml).
  const [targetUrl, setTargetUrl] = useState("http://notes-target:8001");
  const [framework, setFramework] = useState<Framework>("generic");
  const [testToken, setTestToken] = useState("");
  const [spec, setSpec] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onCreated(
        await createScan({
          target_url: targetUrl,
          spec,
          framework,
          test_token: testToken.trim() || undefined,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function loadFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) setSpec(await file.text());
    e.target.value = "";
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-300">Target API URL</label>
        <input
          value={targetUrl}
          onChange={(e) => setTargetUrl(e.target.value)}
          className="w-full rounded-xl border border-slate-700 bg-slate-900/60 px-4 py-2.5 text-sm outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-400/30"
          placeholder="http://notes-target:8001"
        />
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-300">Your framework</label>
        <select
          value={framework}
          onChange={(e) => setFramework(e.target.value as Framework)}
          className="w-full rounded-xl border border-slate-700 bg-slate-900/60 px-4 py-2.5 text-sm outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-400/30"
        >
          {Object.entries(FRAMEWORKS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-slate-500">The report's fix advice is written for this framework.</p>
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-300">
          Test account token <span className="font-normal text-slate-500">(optional)</span>
        </label>
        <input
          value={testToken}
          onChange={(e) => setTestToken(e.target.value)}
          type="password"
          className="w-full rounded-xl border border-slate-700 bg-slate-900/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-400/30"
          placeholder="Bearer token for a throwaway test account"
        />
        <p className="mt-1 text-xs text-slate-500">
          Log in to your target as a disposable test account yourself and paste its token. Some checks
          (like object-level access) need a logged-in session to run; without one they're skipped with a
          note instead of guessed at. We never attempt to log in or guess credentials for you.
        </p>
      </div>

      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <label className="text-sm font-medium text-slate-300">OpenAPI spec (YAML or JSON)</label>
          <div className="flex gap-2 text-xs">
            <button
              type="button"
              onClick={() => setSpec(SAMPLE_SPEC)}
              className="rounded-lg border border-slate-700 px-2.5 py-1 text-slate-300 transition hover:border-indigo-400 hover:text-white"
            >
              Load sample
            </button>
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              className="rounded-lg border border-slate-700 px-2.5 py-1 text-slate-300 transition hover:border-indigo-400 hover:text-white"
            >
              Upload file
            </button>
            <input ref={fileInput} type="file" accept=".yaml,.yml,.json" onChange={loadFile} hidden />
          </div>
        </div>
        <textarea
          value={spec}
          onChange={(e) => setSpec(e.target.value)}
          spellCheck={false}
          className="h-64 w-full resize-y rounded-xl border border-slate-700 bg-slate-950/70 px-4 py-3 font-mono text-xs leading-relaxed outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-400/30"
          placeholder="Paste your openapi.yaml here, or use Load sample"
        />
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={busy || !spec.trim() || !targetUrl.trim()}
        className="w-full rounded-xl bg-indigo-500 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? "Starting…" : "Start scan"}
      </button>
    </form>
  );
}
