import { useEffect, useState } from "react";

import { ApiError, FRAMEWORKS, getScan, type ReportSection, type ScanDetail } from "../api";

// Shown when a scan has completed. Loads the report from GET /scans/{id} (saved there by the worker).
export default function ReportView({ scanId }: { scanId: string }) {
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getScan(scanId)
      .then(setScan)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the report."));
  }, [scanId]);

  if (error) return <div className="text-sm text-rose-200">{error}</div>;
  if (!scan) return <div className="text-sm text-slate-500">Loading the report…</div>;
  if (!scan.report) return <div className="text-sm text-slate-500">This scan has no report.</div>;

  return (
    <div className="space-y-4">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Report</div>
        <p className="mt-1 text-sm text-slate-300">{scan.report.summary}</p>
        <p className="mt-0.5 text-xs text-slate-500">
          Fix advice for {FRAMEWORKS[scan.framework]}, written by an AI model from the numbered OWASP
          sources. Check it against the sources before applying it.
        </p>
      </div>
      {scan.report.sections.map((section) => (
        <Section key={section.check} section={section} />
      ))}
    </div>
  );
}

const OUTCOME_LABEL: Record<string, string> = {
  not_run: "not built yet",
  skipped: "skipped by you",
  pass: "passed",
  fail: "failed",
  needs_review: "needs review",
  error: "could not run",
};

const OUTCOME_STYLE: Record<string, string> = {
  fail: "border-rose-400/50 bg-rose-500/15 text-rose-200",
  pass: "border-emerald-400/40 bg-emerald-500/10 text-emerald-200",
  needs_review: "border-amber-400/40 bg-amber-500/10 text-amber-200",
};

function Section({ section }: { section: ReportSection }) {
  return (
    <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-slate-100">{section.name}</h3>
        <div className="flex gap-1.5">
          {Object.entries(section.counts).map(([outcome, n]) => (
            <span
              key={outcome}
              className={`rounded-full border px-2 py-0.5 text-xs ${
                OUTCOME_STYLE[outcome] ?? "border-slate-700 text-slate-400"
              }`}
            >
              {n} {OUTCOME_LABEL[outcome] ?? outcome}
            </span>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {section.endpoints.map((e) => (
          <code key={e} className="rounded bg-slate-800/70 px-1.5 py-0.5 text-xs text-slate-300">
            {e}
          </code>
        ))}
      </div>

      {section.advice ? (
        // whitespace-pre-line keeps the model's line breaks (its lists), instead of one long paragraph
        <p className="whitespace-pre-line text-sm leading-relaxed text-slate-200">
          <Cited text={section.advice} />
        </p>
      ) : (
        <p className="text-sm text-amber-200/80">{section.note}</p>
      )}

      {section.sources.length > 0 && (
        <ol className="space-y-1 border-t border-slate-800 pt-3 text-xs">
          {section.sources.map((s) => (
            <li key={s.n} className={s.cited ? "text-slate-300" : "text-slate-500"}>
              [{s.n}]{" "}
              <a href={s.url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
                {s.heading}
              </a>
              {s.cited && <span className="ml-2 rounded bg-emerald-500/15 px-1.5 py-0.5 text-emerald-300">cited</span>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

// Turns "**Check ownership** on every request [2]." into bold text with a small [2] badge.
// The model writes a little Markdown; we render only **bold** and [n] (React escapes everything
// else, so model text can never inject HTML into the page).
function Cited({ text }: { text: string }) {
  const parts = text.split(/(\[\d+\]|\*\*[^*]+\*\*)/); // keep [n] and **bold** pieces as separate items
  return (
    <>
      {parts.map((part, i) => {
        if (/^\[\d+\]$/.test(part)) {
          return (
            <sup key={i} className="ml-0.5 rounded bg-indigo-500/20 px-1 text-[10px] font-semibold text-indigo-200">
              {part.slice(1, -1)}
            </sup>
          );
        }
        if (/^\*\*[^*]+\*\*$/.test(part)) {
          return (
            <strong key={i} className="font-semibold text-slate-50">
              {part.slice(2, -2)}
            </strong>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}
