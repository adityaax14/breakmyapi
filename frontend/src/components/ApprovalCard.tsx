import { useEffect, useState } from "react";

import { ApiError, answerApproval, getScan, type PlannedTest, type Scan } from "../api";

// Shown while a scan is "waiting_approval". Loads the agent's question, lists the tests that could
// change data, and sends the answer. After answering, the scan re-queues and the live log continues.
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
    <div className="rounded-xl border border-amber-400/25 bg-amber-500/[0.06] p-5">
      <div className="flex items-center gap-2">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-400/20 text-xs text-amber-300">
          !
        </span>
        <div className="text-sm font-semibold text-amber-100">Approval needed</div>
      </div>
      <p className="mt-1.5 text-sm text-amber-200/70">
        These tests use methods that can change data on your API. Nothing has been sent yet.
      </p>

      {tests === null && !error && <div className="mt-3 text-sm text-amber-200/60">Loading…</div>}
      {tests && (
        <ul className="mono mt-4 space-y-1 text-xs">
          {tests.map((t) => (
            <li key={t.key} className="flex items-center gap-2">
              <span className="w-14 shrink-0 font-semibold text-amber-300">{t.method}</span>
              <span className="text-amber-50">{t.path}</span>
              <span className="text-amber-200/50">· {t.check}</span>
            </li>
          ))}
        </ul>
      )}

      {error && <div className="mt-3 text-sm text-rose-300">{error}</div>}

      <div className="mt-5 flex gap-3">
        <button
          disabled={busy || !tests}
          onClick={() => decide("approve")}
          className="btn flex-1 bg-amber-400 text-black hover:bg-amber-300"
        >
          Approve these tests
        </button>
        <button
          disabled={busy || !tests}
          onClick={() => decide("reject")}
          className="btn flex-1 border border-amber-400/30 text-amber-100 hover:bg-amber-500/10"
        >
          Skip them
        </button>
      </div>
    </div>
  );
}
