import { useState, type FormEvent } from "react";

import { ApiError, logIn, signUp, type User } from "../api";

// One form, two modes: "log in" and "create account". Both end with a token saved by api.ts.
export default function Login({ onLoggedIn }: { onLoggedIn: (user: User) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault(); // stop the browser's default "reload the page" on submit
    setBusy(true);
    setError(null);
    try {
      const user = mode === "login" ? await logIn(email, password) : await signUp(email, password);
      onLoggedIn(user);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const input =
    "w-full rounded-xl border border-slate-700 bg-slate-950/60 px-4 py-2.5 text-sm text-slate-100 outline-none transition focus:border-indigo-400";

  return (
    <form onSubmit={submit} className="mx-auto max-w-sm space-y-5 py-4">
      <div>
        <h2 className="text-lg font-semibold">{mode === "login" ? "Log in" : "Create your account"}</h2>
        <p className="mt-1 text-sm text-slate-400">
          Your scans and verified APIs are private to your account.
        </p>
      </div>

      <label className="block space-y-1.5">
        <span className="text-sm text-slate-300">Email</span>
        <input
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={input}
        />
      </label>

      <label className="block space-y-1.5">
        <span className="text-sm text-slate-300">Password</span>
        <input
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          required
          minLength={mode === "signup" ? 10 : undefined}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={input}
        />
        {mode === "signup" && <span className="text-xs text-slate-500">At least 10 characters.</span>}
      </label>

      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={busy}
        className="w-full rounded-xl bg-indigo-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-400 disabled:opacity-50"
      >
        {busy ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
      </button>

      <button
        type="button"
        onClick={() => {
          setMode(mode === "login" ? "signup" : "login");
          setError(null);
        }}
        className="w-full text-center text-sm text-slate-400 transition hover:text-white"
      >
        {mode === "login" ? "No account yet? Create one" : "Already have an account? Log in"}
      </button>
    </form>
  );
}
