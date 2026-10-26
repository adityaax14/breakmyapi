// The ONLY file that talks to the backend. Every request goes through request().
// The types below mirror the backend's pydantic models (ScanCreate and ScanOut):
// they are the "contract" between the two programs.

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type ScanStatus = "queued" | "running" | "waiting_approval" | "completed" | "failed" | "cancelled";

export interface Scan {
  id: string;
  target_url: string;
  status: ScanStatus;
}

// The frameworks the backend accepts (ScanCreate.framework); the report's fixes are written for it.
export const FRAMEWORKS = {
  generic: "Other / not sure",
  fastapi: "FastAPI (Python)",
  django: "Django REST Framework (Python)",
  express: "Express (Node.js)",
  spring: "Spring Boot (Java)",
} as const;
export type Framework = keyof typeof FRAMEWORKS;

export interface ScanCreate {
  target_url: string;
  spec: string;
  framework: Framework;
  test_token?: string; // optional: a bearer token for a throwaway test account on the target
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

// ---- the login token ----
// Kept in localStorage, so a page refresh keeps you logged in. Storage can be blocked
// (private windows), so every access is wrapped in try/catch.

const TOKEN_KEY = "breakmyapi-token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage blocked: you stay logged in only until the page is closed */
  }
}

// The App listens here, so ANY 401 (an expired session) sends you back to the login screen.
const loggedOutListeners = new Set<() => void>();
export const onLoggedOut = (listener: () => void) => {
  loggedOutListeners.add(listener);
  return () => {
    loggedOutListeners.delete(listener);
  };
};

// Every request carries "Authorization: Bearer <token>" when we have one.
function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const started = performance.now();
  let res: Response;
  try {
    res = await fetch(API + path, {
      method,
      headers: { ...authHeaders(), ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    record({ method, path, status: "network error", ms: Math.round(performance.now() - started) });
    console.error(err);
    throw new ApiError("Could not reach the API. Is the backend running? (Check the browser console.)");
  }
  record({ method, path, status: res.status, ms: Math.round(performance.now() - started) });

  const data = await res.json().catch(() => null);
  if (res.status === 401 && getToken()) {
    // We sent a token and the server refused it: the session expired or was ended.
    setToken(null);
    loggedOutListeners.forEach((l) => l());
  }
  if (!res.ok) {
    throw new ApiError(describeDetail(data?.detail) ?? `Request failed with status ${res.status}`);
  }
  return data as T;
}

// ---- accounts ----

export interface User {
  id: string;
  email: string;
}

interface LoginResult {
  token: string;
  user: User;
}

export async function signUp(email: string, password: string): Promise<User> {
  const result = await request<LoginResult>("POST", "/auth/signup", { email, password });
  setToken(result.token);
  return result.user;
}

export async function logIn(email: string, password: string): Promise<User> {
  const result = await request<LoginResult>("POST", "/auth/login", { email, password });
  setToken(result.token);
  return result.user;
}

export async function logOut() {
  try {
    await request<void>("POST", "/auth/logout");
  } finally {
    setToken(null); // forget the token even if the server could not be reached
  }
}

export const getMe = () => request<User>("GET", "/auth/me");

export const createScan = (body: ScanCreate) => request<Scan>("POST", "/scans", body);
export const cancelScan = (id: string) => request<Scan>("POST", `/scans/${id}/cancel`);

// ---- approval: the agent asks before running tests that could change data ----

export interface PlannedTest {
  key: string;
  check: string;
  method: string;
  path: string;
}

// GET /scans/{id} returns a bit more than a list row: the pending question, if any.
export interface ScanDetail extends Scan {
  approval_request: { tests: PlannedTest[] } | null;
  approval: "approve" | "reject" | null;
  framework: Framework;
  report: ScanReport | null; // filled once the scan has completed
}

// The finished report: one section per check type that was tested.
export interface ReportSource {
  n: number; // the [n] the advice uses to cite it
  heading: string;
  url: string;
  cited: boolean; // did the advice actually cite this source?
}

export interface ReportSection {
  check: string;
  name: string;
  counts: Record<string, number>; // e.g. {"not_run": 3, "skipped": 1}
  endpoints: string[];
  advice: string | null; // null when the model was unavailable or the library had nothing
  sources: ReportSource[];
  note: string;
}

export interface ScanReport {
  summary: string;
  sections: ReportSection[];
}

export const getScan = (id: string) => request<ScanDetail>("GET", `/scans/${id}`);

export const answerApproval = (id: string, decision: "approve" | "reject") =>
  request<ScanDetail>("POST", `/scans/${id}/approval`, { decision });

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
//
// Why fetch and not the browser's EventSource? EventSource cannot send headers, so it could
// not send our login token. fetch can, and it lets us read the reply piece by piece as it arrives.
export function streamScan(
  id: string,
  onEvent: (event: ScanEvent) => void,
  onDone: (status: ScanStatus) => void,
  onError: () => void,
): () => void {
  const path = `/scans/${id}/stream`;
  record({ method: "GET", path, status: "stream", ms: 0 });
  const controller = new AbortController(); // lets us hang up the connection later

  (async () => {
    try {
      const res = await fetch(API + path, { headers: authHeaders(), signal: controller.signal });
      if (!res.ok || !res.body) throw new Error(`stream failed with status ${res.status}`);

      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read(); // waits until the server sends more
        if (done) return;
        buffer += value;

        // SSE messages end with a blank line ("\n\n"). Handle each complete one; keep the rest.
        let end;
        while ((end = buffer.indexOf("\n\n")) !== -1) {
          const message = buffer.slice(0, end);
          buffer = buffer.slice(end + 2);

          // A message looks like:  "event: done\ndata: {...}"  ("event:" is optional)
          let event = "message";
          let data = "";
          for (const line of message.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (event === "done") {
            controller.abort(); // finished: hang up
            onDone(JSON.parse(data).status);
            return;
          }
          onEvent(JSON.parse(data));
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) onError(); // hanging up ourselves is not an error
    }
  })();

  return () => controller.abort();
}
