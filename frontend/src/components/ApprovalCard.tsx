import { useEffect, useState } from "react";

import { ApiError, answerApproval, getScan, type PlannedTest, type Scan } from "../api";

// Shown while a scan is "waiting_approval". It loads the agent's question (GET /scans/{id}),
// lists the tests that could change data, and sends the answer (POST /scans/{id}/approval).
// After answering, the scan goes back in the queue and the live log continues by itself.
export default function ApprovalCard({ scanId, onAnswered }: { scanId: string; onAnswered: (scan: Scan) => void }) {
  const [tests, setTests] = useState<PlannedTest[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getScan(scanId)
      .then((scan) => setTests(scan.approval_request?.tests ?? []))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the question."));
  }, [scanId]);

  async function decide(decision: "approve" | "reject") {
    setBusy(true);
    setError(null);
    try {
      onAnswered(await answerApproval(scanId, decision));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send your answer.");
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4 rounded-xl border border-amber-400/40 bg-amber-500/10 p-4">
      <div>
        <div className="font-semibold text-amber-100">The agent is waiting for your approval</div>
        <p className="mt-1 text-sm text-amber-200/80">
          These tests use methods that can change data on your API. Nothing has been sent yet.
        </p>
      </div>

      {tests === null && !error && <div className="text-sm text-amber-200/70">Loading…</div>}
      {tests && (
        <ul className="space-y-1 font-mono text-xs text-amber-50">
          {tests.map((t) => (
            <li key={t.key}>
              <span className="text-amber-300">{t.method}</span> {t.path}{" "}
              <span className="text-amber-200/60">· {t.check}</span>
            </li>
          ))}
        </ul>
      )}

      {error && <div className="text-sm text-rose-200">{error}</div>}

      <div className="flex gap-3">
        <button
          disabled={busy || !tests}
          onClick={() => decide("approve")}
          className="flex-1 rounded-xl bg-amber-400 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-amber-300 disabled:opacity-50"
        >
          Approve these tests
        </button>
        <button
          disabled={busy || !tests}
          onClick={() => decide("reject")}
          className="flex-1 rounded-xl border border-amber-400/50 px-4 py-2 text-sm text-amber-100 transition hover:bg-amber-500/10 disabled:opacity-50"
        >
          Skip them
        </button>
      </div>
    </div>
  );
}
