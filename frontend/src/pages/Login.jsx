import { useContext, useState } from "react";
import { postJSON } from "../lib/api";
import { AuthContext } from "../lib/auth";

/**
 * Sign in / create account — the wall App.jsx renders (in multiuser mode)
 * until a session exists. Both submit paths set the session cookie server-side;
 * on success we just re-probe /api/v1/me and the wall drops, leaving the user
 * on whatever URL they originally asked for.
 */
export default function Login() {
  const { refresh } = useContext(AuthContext);
  const [mode, setMode] = useState("login"); // login | signup
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await postJSON(`/api/v1/auth/${mode === "signup" ? "signup" : "login"}`,
                     { email: email.trim(), password });
      await refresh(); // flips AuthContext to signed-in; the wall unmounts
    } catch (err) {
      setError(String(err.message || err));
      setBusy(false);
    }
  };

  const switchMode = (m) => {
    setMode(m);
    setError(null);
  };

  return (
    <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface p-6 relative overflow-hidden">
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-primary/5 rounded-full blur-[100px] pointer-events-none"></div>

      <div className="relative w-full max-w-[420px] p-10 rounded-3xl bg-surface-container-lowest/60 backdrop-blur-xl border border-outline-variant/40 shadow-2xl shadow-primary/10 flex flex-col gap-6">
        <div className="flex flex-col items-center gap-4">
          <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center border border-primary/20 shadow-inner">
            <span className="material-symbols-outlined text-primary text-[32px]">
              {mode === "signup" ? "person_add" : "lock_open"}
            </span>
          </div>
          <div className="space-y-1 text-center">
            <h2 className="font-display-lg text-2xl text-on-surface font-bold tracking-tight">
              {mode === "signup" ? "Create your account" : "Welcome back"}
            </h2>
            <p className="text-sm text-on-surface-variant font-body">
              {mode === "signup"
                ? "Sign up to start analyzing repositories."
                : "Sign in to continue to RepoLens."}
            </p>
          </div>
        </div>

        {/* mode toggle */}
        <div className="flex p-1 bg-surface-container-lowest rounded border border-outline-variant">
          {[["login", "Sign In"], ["signup", "Sign Up"]].map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => switchMode(value)}
              className={`flex-1 py-2 text-label rounded transition-all ${mode === value
                ? "bg-primary text-on-primary font-bold"
                : "text-on-surface-variant hover:text-on-surface"}`}
            >
              {label}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <label className="text-label text-on-surface-variant" htmlFor="authEmail">Email</label>
            <input
              id="authEmail"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full bg-surface-container-lowest border border-outline-variant rounded px-3 py-2.5 text-body font-code focus:outline-none focus:border-primary placeholder:text-on-surface-variant/40"
            />
          </div>
          <div className="space-y-2">
            <label className="text-label text-on-surface-variant" htmlFor="authPassword">
              Password{mode === "signup" && <span className="text-on-surface-variant/60"> (min 8 characters)</span>}
            </label>
            <input
              id="authPassword"
              type="password"
              required
              minLength={mode === "signup" ? 8 : undefined}
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full bg-surface-container-lowest border border-outline-variant rounded px-3 py-2.5 text-body font-code focus:outline-none focus:border-primary placeholder:text-on-surface-variant/40"
            />
          </div>

          {error && (
            <div className="p-2.5 bg-red-500/10 text-red-400 text-label rounded text-center border border-red-500/20 break-words">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full bg-primary text-on-primary py-3 font-bold rounded hover:opacity-90 transition-opacity uppercase tracking-widest text-label glow-primary disabled:opacity-50"
          >
            {busy ? "Please wait…" : mode === "signup" ? "Create Account" : "Sign In"}
          </button>
        </form>

        <p className="text-[11px] text-on-surface-variant text-center font-body">
          {mode === "signup" ? "Already have an account? " : "New to RepoLens? "}
          <button
            type="button"
            onClick={() => switchMode(mode === "signup" ? "login" : "signup")}
            className="text-primary hover:underline font-bold"
          >
            {mode === "signup" ? "Sign in" : "Create one"}
          </button>
        </p>
      </div>
    </div>
  );
}
