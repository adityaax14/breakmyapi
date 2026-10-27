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
    e.preventDefault();
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

  return (
    <form onSubmit={submit} className="mx-auto max-w-sm space-y-6 py-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">
          {mode === "login" ? "Welcome back" : "Create your account"}
        </h2>
        <p className="mt-1.5 text-sm text-zinc-500">Your scans and verified APIs are private to your account.</p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="label">Email</label>
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="field"
          />
        </div>
        <div>
          <label className="label">Password</label>
          <input
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={mode === "signup" ? 10 : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="field"
          />
          {mode === "signup" && <p className="hint">At least 10 characters.</p>}
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/[0.07] px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      <button type="submit" disabled={busy} className="btn btn-primary w-full py-3">
        {busy ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
      </button>

      <button
        type="button"
        onClick={() => {
          setMode(mode === "login" ? "signup" : "login");
          setError(null);
        }}
        className="w-full text-center text-sm text-zinc-500 transition hover:text-zinc-200"
      >
        {mode === "login" ? "No account yet? Create one" : "Already have an account? Log in"}
      </button>
    </form>
  );
}
