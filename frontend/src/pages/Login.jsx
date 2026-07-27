import { useContext, useState } from "react";
import { postJSON } from "../lib/api";
import { AuthContext } from "../lib/auth";

/**
 * Sign in / create account — the wall App.jsx renders (in multiuser mode)
 * until a session exists.
 *
 * Login is one step. Signup is two: POST /auth/signup emails a verification
 * code and creates nothing (202), then POST /auth/signup/verify exchanges the
 * code for the account and the session cookie (201). So this form has three
 * modes, and only "login" and "verify" end with a session — after either we
 * just re-probe /api/v1/me and the wall drops, leaving the user on whatever
 * URL they originally asked for.
 *
 * The password stays in state through the verify step because re-requesting a
 * code is the same POST as the first one (that endpoint is also the resend).
 */
export default function Login() {
  const { refresh } = useContext(AuthContext);
  const [mode, setMode] = useState("login"); // login | signup | verify
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [pendingEmail, setPendingEmail] = useState("");
  const [expiresIn, setExpiresIn] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "verify") {
        await postJSON("/api/v1/auth/signup/verify",
                       { email: pendingEmail, code: code.trim() });
        await refresh(); // flips AuthContext to signed-in; the wall unmounts
        return;
      }
      if (mode === "signup") {
        // 202 — no session yet, so don't refresh(); collect the code instead
        const sent = await postJSON("/api/v1/auth/signup",
                                    { email: email.trim(), password });
        setPendingEmail(sent?.email || email.trim().toLowerCase());
        setExpiresIn(sent?.expires_in_mins ?? 10);
        setCode("");
        setMode("verify");
        setBusy(false);
        return;
      }
      await postJSON("/api/v1/auth/login", { email: email.trim(), password });
      await refresh();
    } catch (err) {
      setError(String(err.message || err));
      setBusy(false);
    }
  };

  const resend = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const sent = await postJSON("/api/v1/auth/signup",
                                  { email: pendingEmail, password });
      setExpiresIn(sent?.expires_in_mins ?? 10);
      setCode("");
      setNotice("A new code is on its way — the previous one no longer works.");
    } catch (err) {
      // 429 here is the cooldown, and its detail already says how long to wait
      setError(String(err.message || err));
    }
    setBusy(false);
  };

  const switchMode = (m) => {
    setMode(m);
    setError(null);
    setNotice(null);
    setCode("");
  };

  const heading = {
    login: ["lock_open", "Welcome back", "Sign in to continue to RepoLens."],
    signup: ["person_add", "Create your account",
             "Sign up to start analyzing repositories."],
    verify: ["mark_email_unread", "Check your email",
             `We sent a 6-digit code to ${pendingEmail}.`],
  }[mode];

  return (
    <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface p-6 relative overflow-hidden">
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-primary/5 rounded-full blur-[100px] pointer-events-none"></div>

      <div className="relative w-full max-w-[420px] p-10 rounded-3xl bg-surface-container-lowest/60 backdrop-blur-xl border border-outline-variant/40 shadow-2xl shadow-primary/10 flex flex-col gap-6">
        <div className="flex flex-col items-center gap-4">
          <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center border border-primary/20 shadow-inner">
            <span className="material-symbols-outlined text-primary text-[32px]">
              {heading[0]}
            </span>
          </div>
          <div className="space-y-1 text-center">
            <h2 className="font-display-lg text-2xl text-on-surface font-bold tracking-tight">
              {heading[1]}
            </h2>
            <p className="text-sm text-on-surface-variant font-body break-words">
              {heading[2]}
            </p>
          </div>
        </div>

        {/* mode toggle — hidden mid-verification, where the only ways out are
            entering the code or starting over */}
        {mode !== "verify" && (
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
        )}

        <form onSubmit={submit} className="space-y-4">
          {mode === "verify" ? (
            <div className="space-y-2">
              <label className="text-label text-on-surface-variant" htmlFor="authCode">
                Verification code
                <span className="text-on-surface-variant/60"> (expires in {expiresIn} min)</span>
              </label>
              <input
                id="authCode"
                type="text"
                required
                autoFocus
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength={6}
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                placeholder="000000"
                className="w-full bg-surface-container-lowest border border-outline-variant rounded px-3 py-2.5 text-center text-2xl tracking-[0.5em] font-code focus:outline-none focus:border-primary placeholder:text-on-surface-variant/30"
              />
            </div>
          ) : (
            <>
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
            </>
          )}

          {notice && (
            <div className="p-2.5 bg-primary/10 text-primary text-label rounded text-center border border-primary/20 break-words">
              {notice}
            </div>
          )}
          {error && (
            <div className="p-2.5 bg-red-500/10 text-red-400 text-label rounded text-center border border-red-500/20 break-words">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy || (mode === "verify" && code.length < 6)}
            className="w-full bg-primary text-on-primary py-3 font-bold rounded hover:opacity-90 transition-opacity uppercase tracking-widest text-label glow-primary disabled:opacity-50"
          >
            {busy
              ? "Please wait…"
              : mode === "verify"
                ? "Verify & Continue"
                : mode === "signup"
                  ? "Send Code"
                  : "Sign In"}
          </button>
        </form>

        {mode === "verify" ? (
          <p className="text-[11px] text-on-surface-variant text-center font-body">
            Didn&apos;t get it?{" "}
            <button
              type="button"
              onClick={resend}
              disabled={busy}
              className="text-primary hover:underline font-bold disabled:opacity-50"
            >
              Resend code
            </button>
            {" · "}
            <button
              type="button"
              onClick={() => switchMode("signup")}
              className="text-primary hover:underline font-bold"
            >
              Use a different email
            </button>
          </p>
        ) : (
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
        )}
      </div>
    </div>
  );
}
