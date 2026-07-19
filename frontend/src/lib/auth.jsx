import { createContext, useCallback, useEffect, useState } from "react";
import { API_BASE, postJSON } from "./api";

/**
 * Session state for the whole app, resolved from GET /api/v1/me:
 *
 *   mode: "loading"   — first probe in flight (render nothing gate-related)
 *         "single"    — MULTIUSER=false on the server: no accounts, no wall
 *         "multiuser" — accounts exist; `user` is null until signed in
 *
 * Uses a raw fetch (not getJSON) on purpose: the three outcomes are HTTP
 * statuses (200 signed-in / 401 anonymous / 503 disabled) and the probe must
 * never be served from the client cache.
 */
export const AuthContext = createContext({
  mode: "loading", user: null,
  refresh: () => {}, logout: async () => {},
});

export function AuthProvider({ children }) {
  const [state, setState] = useState({ mode: "loading", user: null });

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(API_BASE + "/api/v1/me");
      if (res.ok) {
        const me = await res.json();
        setState({ mode: "multiuser", user: me.user });
      } else if (res.status === 503) {
        setState({ mode: "single", user: null });
      } else {
        setState({ mode: "multiuser", user: null });
      }
    } catch {
      // backend down: behave like single-user so pages show their own errors
      setState({ mode: "single", user: null });
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await postJSON("/api/v1/auth/logout");
    } catch {
      // session already gone server-side — still drop it client-side
    }
    setState({ mode: "multiuser", user: null });
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
