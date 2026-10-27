import { useEffect, useState } from "react";

import { ApiError, FRAMEWORKS, getScan, type ReportSection, type ScanDetail } from "../api";

export default function ReportView({ scanId }: { scanId: string }) {
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getScan(scanId)
      .then(setScan)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the report."));
  }, [scanId]);

  if (error) return <div className="text-sm text-rose-300">{error}</div>;
  if (!scan) return <div className="py-6 text-center text-sm text-zinc-500">Loading the report…</div>;
  if (!scan.report) return <div className="py-6 text-center text-sm text-zinc-500">This scan has no report.</div>;

  // Roll every section's counts into one headline tally.
  const totals: Record<string, number> = {};
  for (const s of scan.report.sections)
    for (const [k, n] of Object.entries(s.counts)) totals[k] = (totals[k] ?? 0) + n;

  return (
    <div className="space-y-5">
      {/* ---- headline ---- */}
      <div className="card-inset p-5">
        <div className="flex items-center justify-between gap-3">
          <div className="eyebrow">Report</div>
          <span className="chip">{FRAMEWORKS[scan.framework]}</span>
        </div>
        <div className="mt-3 flex flex-wrap items-baseline gap-x-6 gap-y-2">
          {ORDER.filter((o) => totals[o]).map((o) => (
            <div key={o} className="flex items-baseline gap-2">
              <span className={`text-2xl font-bold tabular-nums ${BIG_COLOR[o] ?? "text-zinc-200"}`}>{totals[o]}</span>
              <span className="text-sm text-zinc-500">{OUTCOME_LABEL[o] ?? o}</span>
            </div>
          ))}
        </div>
        <p className="mt-3 border-t border-white/5 pt-3 text-xs leading-relaxed text-zinc-500">
          Fix advice is written by an AI model from the numbered OWASP sources below. Verify it against the
          sources before applying.
        </p>
      </div>

      {scan.report.sections.map((section) => (
        <Section key={section.check} section={section} />
      ))}
    </div>
  );
}

const ORDER = ["fail", "needs_review", "error", "pass", "skipped", "not_run"];

const OUTCOME_LABEL: Record<string, string> = {
  not_run: "not built yet",
  skipped: "skipped",
  pass: "passed",
  fail: "failed",
  needs_review: "needs review",
  error: "could not run",
};

const BIG_COLOR: Record<string, string> = {
  fail: "text-rose-400",
  needs_review: "text-amber-400",
  pass: "text-emerald-400",
};

const PILL_STYLE: Record<string, string> = {
  fail: "border-rose-400/40 bg-rose-500/10 text-rose-300",
  pass: "border-emerald-400/30 bg-emerald-500/10 text-emerald-300",
  needs_review: "border-amber-400/30 bg-amber-500/10 text-amber-300",
  error: "border-white/15 bg-white/[0.03] text-zinc-400",
};

// The single most important verdict in a section, for the header dot + accent.
function dominant(counts: Record<string, number>): string {
  for (const o of ORDER) if (counts[o]) return o;
  return "pass";
}

const DOT: Record<string, string> = {
  fail: "bg-rose-400",
  needs_review: "bg-amber-400",
  pass: "bg-emerald-400",
  error: "bg-zinc-500",
  skipped: "bg-zinc-600",
  not_run: "bg-zinc-600",
};

function Section({ section }: { section: ReportSection }) {
  const top = dominant(section.counts);
  return (
    <section className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-4">
        <div className="flex items-center gap-2.5">
          <span className={`h-2 w-2 rounded-full ${DOT[top] ?? "bg-zinc-500"}`} />
          <h3 className="font-semibold tracking-tight text-zinc-100">{section.name}</h3>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {ORDER.filter((o) => section.counts[o]).map((o) => (
            <span
              key={o}
              className={`rounded-full border px-2 py-0.5 text-xs ${PILL_STYLE[o] ?? "border-white/15 text-zinc-400"}`}
            >
              {section.counts[o]} {OUTCOME_LABEL[o] ?? o}
            </span>
          ))}
        </div>
      </div>

      <div className="space-y-4 border-t border-white/5 px-5 py-4">
        <div className="flex flex-wrap gap-1.5">
          {section.endpoints.map((e) => (
            <code key={e} className="chip">
              {e}
            </code>
          ))}
        </div>

        {section.advice ? (
          <Advice text={section.advice} />
        ) : (
          <p className="rounded-lg border border-amber-400/20 bg-amber-500/[0.05] px-3 py-2 text-sm text-amber-200/80">
            {section.note}
          </p>
        )}

        {section.sources.length > 0 && (
          <div className="border-t border-white/5 pt-3">
            <div className="eyebrow mb-2">Sources</div>
            <ol className="space-y-1.5 text-xs">
              {section.sources.map((s) => (
                <li key={s.n} className="flex gap-2">
                  <span className={`mono shrink-0 ${s.cited ? "text-zinc-300" : "text-zinc-600"}`}>[{s.n}]</span>
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noreferrer"
                    className={`underline-offset-2 hover:underline ${s.cited ? "text-zinc-300" : "text-zinc-600"}`}
                  >
                    {s.heading}
                  </a>
                  {s.cited && (
                    <span className="ml-auto shrink-0 rounded bg-emerald-500/10 px-1.5 text-[10px] text-emerald-400">
                      cited
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </section>
  );
}

// Render the model's advice as a clean list. It writes lines like "1. **Validate** the token [2]"
// or "- cherry-pick fields". We split into lines, strip the marker, and render inline **bold** + [n].
function Advice({ text }: { text: string }) {
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

  const items = lines.map((line) => {
    const listMatch = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/);
    return { isItem: !!listMatch, content: listMatch ? listMatch[1] : line };
  });

  // If most lines are list items, render a proper list; otherwise flowing paragraphs.
  const listish = items.filter((i) => i.isItem).length >= 2;

  if (listish) {
    return (
      <ol className="space-y-2 text-sm leading-relaxed text-zinc-300">
        {items.map((it, i) =>
          it.isItem ? (
            <li key={i} className="flex gap-2.5">
              <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-zinc-600" />
              <span>
                <Inline text={it.content} />
              </span>
            </li>
          ) : (
            <p key={i} className="text-zinc-400">
              <Inline text={it.content} />
            </p>
          ),
        )}
      </ol>
    );
  }

  return (
    <div className="space-y-2 text-sm leading-relaxed text-zinc-300">
      {items.map((it, i) => (
        <p key={i}>
          <Inline text={it.content} />
        </p>
      ))}
    </div>
  );
}

// Inline formatting: **bold** and [n] citation badges. React escapes everything else, so model
// text can never inject markup into the page.
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\[\d+\]|\*\*[^*]+\*\*)/);
  return (
    <>
      {parts.map((part, i) => {
        if (/^\[\d+\]$/.test(part)) {
          return (
            <sup
              key={i}
              className="mx-0.5 rounded bg-white/10 px-1 text-[10px] font-semibold text-zinc-300 align-super"
            >
              {part.slice(1, -1)}
            </sup>
          );
        }
        if (/^\*\*[^*]+\*\*$/.test(part)) {
          return (
            <strong key={i} className="font-semibold text-white">
              {part.slice(2, -2)}
            </strong>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}
