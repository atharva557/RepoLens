# 07 — Auth & multiuser

The frontend supports three operating modes without any configuration change
on the client side. Everything is driven by a single probe to `GET /api/v1/me`
on startup.

---

## `src/lib/auth.jsx`

### `AuthContext`

```js
export const AuthContext = createContext({
  mode: "loading", user: null,
  refresh: () => {}, logout: async () => {},
});
```

**Context value shape:**

| Field | Type | Meaning |
|---|---|---|
| `mode` | `"loading" \| "single" \| "multiuser"` | Which operating mode the server is in |
| `user` | object \| null | Signed-in account, or `null` if anonymous |
| `refresh()` | function | Re-probe `/me` — called after login to flip the wall |
| `logout()` | async function | POST `/auth/logout` then clear local state |

### `AuthProvider`

```jsx
export function AuthProvider({ children }) {
  const [state, setState] = useState({ mode: "loading", user: null });
  // ...
  return (
    <AuthContext.Provider value={{ ...state, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
```

`AuthProvider` wraps the `BrowserRouter` in `App.jsx` so all routes and
components have access to auth state.

### The startup probe

```js
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
    // backend down: treat as single-user so pages surface their own errors
    setState({ mode: "single", user: null });
  }
}, []);

useEffect(() => { refresh(); }, [refresh]);
```

`refresh` uses a raw `fetch` — **not** `getJSON` — deliberately. The three
outcomes are HTTP status codes, not data shapes, and the result must never be
served from the client GET cache (a stale "anonymous" response would keep the
Login wall up after the user signs in from another tab).

**Why status 503 means single-user:** when `MULTIUSER=false` the backend
returns `503 Service Unavailable` from `/api/v1/me`. This is an explicit
signal, not a failure — the server is up, auth is just disabled.

**Network failure fallback:** if `fetch` throws (backend completely down),
`mode` becomes `"single"`. This is intentional — pages already show their own
errors when the API is unreachable, and keeping `mode === "loading"` forever
would show a blank screen instead.

### The three modes in practice

| `mode` | `user` | What the user sees |
|---|---|---|
| `"loading"` | `null` | `Gate` renders `null` — no flash, no spinner |
| `"single"` | `null` | Full app, no login wall, Navbar has no account chip |
| `"multiuser"` + no user | `null` | `Login` wall on every URL |
| `"multiuser"` + user | object | Full app, Navbar shows account chip + logout |

### `logout`

```js
const logout = useCallback(async () => {
  try {
    await postJSON("/api/v1/auth/logout");
  } catch {
    // session already gone server-side — still drop it client-side
  }
  setState({ mode: "multiuser", user: null });
}, []);
```

The catch block handles the case where the session was already invalidated
server-side (e.g. expired, deleted by an admin). The client clears its state
regardless, so the Login wall appears immediately.

---

## `Login` page (`src/pages/Login.jsx`)

`Login` has no route of its own. It is rendered by `Gate` as the full viewport
content for anonymous multiuser visitors. The currently requested URL stays in
the browser bar — once `refresh()` succeeds (after login or signup/verify),
`Gate` re-renders and `BrowserRouter` delivers that URL.

### Three form modes

`Login` manages a single `mode` state: `"login"` | `"signup"` | `"verify"`.

#### `"login"`

```
POST /api/v1/auth/login  { email, password }
  200 (session cookie set) → refresh() → Gate drops, original URL loads
  401                      → generic error ("Invalid credentials")
```

One generic `401` is returned for all failures (wrong email, wrong password,
unknown account) — no information about whether the email exists is leaked.

#### `"signup"` (step 1 of 2)

```
POST /api/v1/auth/signup  { email, password }
  202 { email, expires_in_mins } → switch to "verify" mode
  429 (resend too soon)          → show cooldown message from detail
```

`202` means the OTP was emailed. **No account exists yet** — the form
transitions to `"verify"` mode and stores `pendingEmail` and `expiresIn`.
`POST /signup` is also the resend endpoint: calling it again within the 60 s
cooldown returns a `429` with the remaining wait; after the cooldown it issues
a new code and the old one is immediately invalidated.

#### `"verify"` (step 2 of 2)

```
POST /api/v1/auth/signup/verify  { email, pendingEmail, code }
  201 (account + session cookie) → refresh() → Gate drops
  400 / 401                      → wrong or expired code
```

`201` is the only response that creates an account and starts a session — so
`refresh()` is the correct next step, exactly as after a successful login.

The code input is `inputMode="numeric"` with `maxLength={6}` and strips
non-digits on change, giving a smooth OTP experience on mobile.

### Mode toggle

The login/signup toggle is a two-button segmented control, hidden while in
`"verify"` mode (the only exits at that point are entering the correct code
or clicking "Use a different email" to restart from `"signup"`).

### Password persistence through verify

The `password` field stays in React state through the `"verify"` step because
`POST /signup` (the resend) requires the original password. Without it, the
Resend button would need to ask for the password again.

---

## Multiuser changes to the rest of the app

The frontend itself does not enforce per-route access control beyond the `Gate`
wall — once signed in, all routes are accessible. Ownership scoping happens
server-side:

- `GET /repos` returns only the requesting user's repos.
- `GET /profiles` returns only the requesting user's profiles.
- Trigger endpoints (`POST /analyze`, etc.) require a session and record
  `created_by`.
- `PUT /config` returns `403` — keys are per-user via `/api/v1/me`.

The dashboard therefore shows each user their own work automatically, without
any client-side filtering. An anonymous user who somehow reaches a `GET` read
endpoint would get the store's global data (the current slice does not
implement hard per-repo ACLs on reads), but they cannot reach any route in the
first place because `Gate` renders `Login` on every URL.

### CSRF in multiuser mode

`postJSON` and `putJSON` always send `X-GitPulse-Client: dashboard`. In
multiuser mode the backend validates this header on every mutating route.
Cross-site form submissions cannot set custom headers, so this prevents
cross-site request forgery without needing a separate token fetch.

### Session cookie

The server sets an `HttpOnly` session cookie on login/verify. The browser
sends it automatically on every same-origin request. `fetch` does not send
cookies cross-origin by default — but all requests go through the Vite proxy
(same origin in dev) or a reverse proxy (same origin in production), so no
`credentials: "include"` flag is needed on any `fetch` call.
