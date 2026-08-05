# 01 — Overview & setup

## What the frontend is

`frontend/` is a Vite + React 19 single-page application. It is a **pure
client** of the FastAPI backend — no server-side rendering, no server process
of its own. Every piece of data comes from `GET /api/...` or `POST /api/...`,
which Vite proxies to `http://127.0.0.1:8000` in development so there are no
hardcoded ports in component code and CORS is never a concern during local
development.

## Directory layout

```
frontend/
├── index.html              # Vite entry — mounts <div id="root">
├── vite.config.js          # build config: React plugin, Tailwind plugin, dev proxy
├── package.json            # dependencies and npm scripts
├── .oxlintrc.json          # oxlint rule config
└── src/
    ├── main.jsx            # createRoot — wraps App in StrictMode
    ├── App.jsx             # ThemeContext provider, AuthProvider, BrowserRouter, Gate
    ├── App.css             # global resets / font imports
    ├── index.css           # Tailwind base + custom CSS tokens
    ├── pages/
    │   ├── Home.jsx
    │   ├── Loading.jsx
    │   ├── Dashboard.jsx
    │   ├── BugHotspots.jsx
    │   ├── DeveloperProfile.jsx
    │   ├── PRReview.jsx
    │   ├── Status.jsx
    │   └── Login.jsx
    ├── components/
    │   ├── Navbar.jsx
    │   ├── SettingsDrawer.jsx
    │   ├── Card.jsx
    │   └── SyncBadge.jsx
    └── lib/
        ├── api.js          # HTTP client, ApiError, GET cache
        ├── auth.jsx        # AuthContext, AuthProvider
        ├── settings.js     # localStorage-backed repo + UI settings
        └── theme.js        # ThemeContext, accentThemeCss, mixHex
```

## Dependencies

```json
"dependencies": {
  "@tailwindcss/vite": "^4.3.2",
  "react":            "^19.2.7",
  "react-dom":        "^19.2.7",
  "react-router-dom": "^7.18.1",
  "recharts":         "^3.9.2",
  "tailwindcss":      "^4.3.2"
}
```

`recharts` is the only charting library — used on the Dashboard (commit-quality
trend `LineChart`, skills `RadarChart`) and the Developer Profile heatmap.
No other runtime dependencies exist outside the React and Tailwind ecosystems.

## Dev server

```bash
cd frontend
npm install
npm run dev          # Vite dev server — http://localhost:5173 (or Tailscale host)
```

The API backend must already be running:

```bash
# from test_1/
python -m uvicorn api.main:app --reload
```

Vite's dev server proxies every `/api` request to `http://127.0.0.1:8000`
(see `vite.config.js` below) so pages fetch `/api/repos` and the browser never
sees the backend port.

## Production build

```bash
npm run build        # outputs to frontend/dist/
npm run preview      # serve the dist build locally for a quick smoke-test
```

`vite build` produces a static bundle in `frontend/dist/`. The FastAPI app does
not serve these files itself in the standard configuration — in production,
point a reverse proxy (nginx, Caddy, etc.) at `dist/` and proxy `/api/` to
uvicorn.

## Linting

```bash
npm run lint         # oxlint — fast Rust-based linter, config in .oxlintrc.json
```

oxlint replaces ESLint for this project. It is significantly faster and covers
the rules used here without a plugin ecosystem.

## `vite.config.js` in full

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,          // listen on all local IPs (needed for Tailscale access)
    port: 5173,
    allowedHosts: ['atharva.tailfbc6c8.ts.net'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
```

Key points:
- `host: true` makes the dev server bind to `0.0.0.0` — required for
  Tailscale (or any remote device on the same network) to reach it.
- `allowedHosts` restricts which hostnames the browser can use to reach the
  dev server. The bare `localhost` / `127.0.0.1` always work; remote names
  must be listed here.
- The proxy strips the `/api` prefix before forwarding to FastAPI, so the
  backend sees `GET /repos` not `GET /api/repos`. This matches the FastAPI
  route definitions exactly.
- **In single-user mode** the API already enables CORS for `*`, so the proxy
  is a convenience, not a requirement — pages would work without it. In
  **multiuser mode** the CORS policy is tightened to `DASHBOARD_ORIGIN`, so
  the proxy (or correct origin configuration) becomes mandatory.
