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
    <form onSubmit={submit} className="space-y-6">
      <div>
        <div className="eyebrow">New scan</div>
        <h2 className="mt-1 text-lg font-semibold tracking-tight">Configure your target</h2>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="label">Target API URL</label>
          <input
            value={targetUrl}
            onChange={(e) => setTargetUrl(e.target.value)}
            className="field mono"
            placeholder="https://api.yoursite.com"
          />
        </div>
        <div>
          <label className="label">Framework</label>
          <div className="relative">
            <select
              value={framework}
              onChange={(e) => setFramework(e.target.value as Framework)}
              className="field appearance-none pr-10"
            >
              {Object.entries(FRAMEWORKS).map(([value, lbl]) => (
                <option key={value} value={value} className="bg-zinc-900">
                  {lbl}
                </option>
              ))}
            </select>
            <span className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-zinc-500">▾</span>
          </div>
        </div>
      </div>

      <div>
        <label className="label">
          Test account token <span className="font-normal text-zinc-600">· optional</span>
        </label>
        <input
          value={testToken}
          onChange={(e) => setTestToken(e.target.value)}
          type="password"
          className="field mono"
          placeholder="Bearer token for a throwaway test account"
        />
        <p className="hint">
          Needed for checks that require a logged-in session (object-level access, mass assignment). Create a
          disposable account on your target, log in yourself, and paste its token. We never log in or guess
          credentials for you.
        </p>
      </div>

      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <label className="label mb-0">OpenAPI spec</label>
          <div className="flex gap-2">
            <button type="button" onClick={() => setSpec(SAMPLE_SPEC)} className="btn btn-ghost px-3 py-1 text-xs">
              Load sample
            </button>
            <button type="button" onClick={() => fileInput.current?.click()} className="btn btn-ghost px-3 py-1 text-xs">
              Upload
            </button>
            <input ref={fileInput} type="file" accept=".yaml,.yml,.json" onChange={loadFile} hidden />
          </div>
        </div>
        <textarea
          value={spec}
          onChange={(e) => setSpec(e.target.value)}
          spellCheck={false}
          className="field mono h-60 resize-y py-3 text-xs leading-relaxed"
          placeholder="Paste your openapi.yaml or .json here — or use Load sample"
        />
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/[0.07] px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      <button type="submit" disabled={busy || !spec.trim() || !targetUrl.trim()} className="btn btn-primary w-full py-3">
        {busy ? "Starting scan…" : "Start scan →"}
      </button>
    </form>
  );
}
