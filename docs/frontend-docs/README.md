# Frontend Documentation

This folder documents the **RepoLens React dashboard** (`frontend/`) in depth.
It is a companion to [09-frontend.md](../09-frontend.md), which gives the
high-level overview. These docs go further: every page's data flow, every
component's contract, the client library internals, theming mechanics, and the
auth gate.

## Stack at a glance

| Concern | Choice |
|---|---|
| Bundler | Vite 8 |
| Framework | React 19 (StrictMode) |
| Styling | Tailwind CSS 4 (via `@tailwindcss/vite` plugin) |
| Routing | react-router-dom 7 |
| Charts | Recharts 3 |
| Linting | oxlint |

The app is a **pure client** of the FastAPI backend — no server-side rendering,
no SSR, no Node.js server. All requests go to `/api/...`, which `vite.config.js`
proxies to `http://127.0.0.1:8000`.

## Reading order

| # | Doc | Covers |
|---|---|---|
| 01 | [Overview & setup](01-overview-and-setup.md) | Directory layout, dev server, build, proxy config |
| 02 | [App shell & routing](02-app-shell-and-routing.md) | `main.jsx`, `App.jsx`, the `Gate` component, theme/accent injection |
| 03 | [Pages](03-pages.md) | Every route: data fetching, loading/error states, user interactions |
| 04 | [Components](04-components.md) | `Navbar`, `SettingsDrawer`, `Card`, `SyncBadge` |
| 05 | [Client library](05-client-library.md) | `api.js` — HTTP wrappers, `ApiError`, GET cache, CSRF header |
| 06 | [Theming & settings](06-theming-and-settings.md) | `theme.js`, `settings.js` — `ThemeContext`, accent palette, localStorage stores |
| 07 | [Auth & multiuser](07-auth-and-multiuser.md) | `auth.jsx` — `AuthContext`, the three modes, the `Gate` wall, `Login` page |
