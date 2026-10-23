// The ONLY file that talks to the backend. Every request goes through request().
// The types below mirror the backend's pydantic models (ScanCreate and ScanOut):
// they are the "contract" between the two programs.

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type ScanStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface Scan {
  id: string;
  target_url: string;
  status: ScanStatus;
}

export interface ScanCreate {
  target_url: string;
  spec: string;
}

export const isFinished = (s: ScanStatus) =>
  s === "completed" || s === "failed" || s === "cancelled";

// ---- a tiny request log, so the UI can show every call the page makes ----

export interface LogEntry {
  id: number;
  time: string;
  method: string;
  path: string;
  status: number | "network error" | "stream";
  ms: number;
}

let entries: LogEntry[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

export const subscribeLog = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
export const getLog = () => entries;

function record(entry: Omit<LogEntry, "id" | "time">) {
  const time = new Date().toLocaleTimeString();
  entries = [{ id: nextId++, time, ...entry }, ...entries].slice(0, 40);
  listeners.forEach((l) => l());
}

// ---- the request helper ----

export class ApiError extends Error {}

// FastAPI sends errors two ways: our own {"detail": "text"} and pydantic's
// {"detail": [{"loc": [...], "msg": "..."}]}. Turn either into one string.
function describeDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => `${(d.loc ?? []).slice(1).join(".") || "body"}: ${d.msg}`)
      .join("; ");
  }
  return null;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const started = performance.now();
  let res: Response;
  try {
    res = await fetch(API + path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    record({ method, path, status: "network error", ms: Math.round(performance.now() - started) });
    console.error(err);
    throw new ApiError("Could not reach the API. Is the backend running? (Check the browser console.)");
  }
  record({ method, path, status: res.status, ms: Math.round(performance.now() - started) });

  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(describeDetail(data?.detail) ?? `Request failed with status ${res.status}`);
  }
  return data as T;
}

export const createScan = (body: ScanCreate) => request<Scan>("POST", "/scans", body);
export const getScan = (id: string) => request<Scan>("GET", `/scans/${id}`);
export const cancelScan = (id: string) => request<Scan>("POST", `/scans/${id}/cancel`);

export interface ScanSummary extends Scan {
  created_at: string;
}

export interface ScanPage {
  items: ScanSummary[];
  total: number;
}

export const PAGE_SIZE = 10;

export const listScans = (page: number) =>
  request<ScanPage>("GET", `/scans?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`);

// ---- the OWASP library (RAG search) ----

export interface CheckInfo {
  id: string;
  name: string;
}

export interface LibraryHit {
  chunk_id: string;
  heading: string;
  url: string;
  score: number;
  text: string;
}

export const getChecks = () => request<CheckInfo[]>("GET", "/library/checks");

export function searchLibrary(q: string, check: string | null) {
  // URLSearchParams turns {q: "role admin"} into "q=role+admin", escaping spaces and symbols safely.
  const params = new URLSearchParams({ q });
  if (check) params.set("check", check);
  return request<LibraryHit[]>("GET", `/library/search?${params}`);
}

export interface AskResult {
  answer: string;
  sources: LibraryHit[]; // numbered [1], [2], ... in this order
  cited: number[];
  tokens: number;
}

export const askLibrary = (question: string, check: string | null) =>
  request<AskResult>("POST", "/library/ask", { question, check });

// ---- live updates (Server-Sent Events) ----

export interface ScanEvent {
  message: string;
  status: ScanStatus;
}

// Opens ONE connection; the server pushes a message every time the scan writes a diary line.
// Returns a function that closes the connection.
export function streamScan(
  id: string,
  onEvent: (event: ScanEvent) => void,
  onDone: (status: ScanStatus) => void,
  onError: () => void,
): () => void {
  const path = `/scans/${id}/stream`;
  record({ method: "GET", path, status: "stream", ms: 0 });

  const source = new EventSource(API + path);
  source.onmessage = (message) => onEvent(JSON.parse(message.data));
  source.addEventListener("done", (message) => {
    source.close(); // finished: close it, or the browser would reconnect by itself
    onDone(JSON.parse((message as MessageEvent).data).status);
  });
  source.onerror = () => {
    source.close();
    onError();
  };
  return () => source.close();
}
