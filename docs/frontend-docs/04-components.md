# 04 — Components

Shared UI building blocks live in `src/components/`. There are four of them —
the codebase deliberately keeps the component count low and composes pages
directly from primitives rather than building a deep component tree.

---

## `Navbar`

**File:** `src/components/Navbar.jsx`  
**Rendered by:** `App.jsx` — always present, fixed at the top of every page.

### Layout

```
<header class="fixed top-0 ... h-[52px]">
  Logo (RepoLens)  |  Nav links (desktop)  |  Right cluster (account + Settings + hamburger)
</header>
```

The header is `position: fixed` and `z-50`. `App.jsx` adds `pt-[52px]` to the
content wrapper to prevent pages from sliding under it.

### Context dependencies

| Context | Fields consumed |
|---|---|
| `AuthContext` | `mode`, `user` (account object), `logout` |
| `useLocation` / `useNavigate` | current path + query string |

`isLoggedIn` is true when `mode === "single"` (no auth required) or when
`Boolean(account)` (authenticated in multiuser mode). The full nav bar is
hidden entirely for anonymous multiuser visitors — `Gate` shows `<Login />`
instead, so there is nothing to navigate to.

### Repository context propagation

The current `repo` query parameter is read from `useLocation`:

```js
const repo = new URLSearchParams(location.search).get("repo");
```

Every context-aware link uses `repoUrl(path, repo)`:

```js
function repoUrl(path, repo) {
  return repo ? `${path}?repo=${encodeURIComponent(repo)}` : path;
}
```

This ensures that clicking Dashboard, Bug Hotspots, or PR Reviews from any
page always carries the currently viewed repository forward. Links that require
a repo but have none (`Dashboard`, `Bug Hotspots`, `PR Reviews`) are rendered
as non-interactive `<span>` elements with a `cursor-not-allowed` style and a
tooltip saying "Choose a repository first."

### Repositories dropdown

A `<div role="menu">` that lists all analyzed repos fetched from
`GET /repos` (30 s client TTL). Clicking an entry navigates to
`/dashboard?repo=<key>`. If no repos exist, an "Analyze a repository →" link
to Home is shown instead. The dropdown closes on any navigation or outside
interaction via `closeMenus()`.

### More dropdown

Groups the per-repo tools (Bug Hotspots, PR Reviews) into a single dropdown to
keep the top bar uncluttered. Items are only `<Link>` when a repo is active;
otherwise they are disabled `<span>` elements.

### Active repo chip

When a repo is in context a small pill — `Repo: owner/repo` — is shown in the
desktop nav. It is truncated at `max-w-36 lg:max-w-48` to avoid overflowing
on long repo names.

### Account cluster (multiuser)

When `mode === "multiuser"` and `account` is set:
- A round avatar chip with the first letter of the GitHub login or email.
- The full login/email displayed at `lg:` breakpoint.
- A logout button (`material-symbols-outlined: logout`) that calls
  `AuthContext.logout()`.

### Settings button

Opens `SettingsDrawer` by setting local `showSettings` state. The button
renders the drawer inline via `<SettingsDrawer open={showSettings} onClose={...} />`.

### Mobile menu

At `md:` and below the full nav collapses into a hamburger. The mobile menu
renders as an absolutely positioned panel below the header with the same links
laid out vertically.

---

## `SettingsDrawer`

**File:** `src/components/SettingsDrawer.jsx`  
**Rendered by:** `Navbar` (via `createPortal` into `document.body`)

### Why a portal

The `Navbar` uses `backdrop-blur-xl`. In CSS, `backdrop-filter` on an ancestor
creates a new stacking context and a new containing block for `position: fixed`
descendants — meaning a `fixed` drawer rendered inside the header would be
clipped to the header's bounds. Rendering through `createPortal` into
`document.body` bypasses this entirely.

### Opening / closing

- Opened by the Settings button in `Navbar`.
- Closes on: ESC keydown, click on the backdrop overlay, or the `×` button.
- While open, `document.body.style.overflow = "hidden"` prevents the page
  behind from scrolling. This is restored in the effect cleanup.
- Slide animation is driven by an **inline `transform` style**, not a Tailwind
  class — several of the project's custom spacing tokens caused Tailwind
  `translate-x-*` utilities to resolve incorrectly, so inline styles are used
  instead:

```js
style={{
  transform: open ? "translateX(0)" : "translateX(100%)",
  transition: "transform 220ms cubic-bezier(0.16, 1, 0.3, 1)",
}}
```

### Sections

#### Appearance

**Theme toggle:** a three-button segmented control (System / Dark / Light).
Changes are applied to `tempSettings` immediately and reflected live on the
page because `App.jsx` reads from `ThemeContext` — but they are only
**persisted** when "Save Changes" is clicked at the bottom of the drawer.

**Accent color picker:** four rows, one per accent (`ACCENTS` from
`settings.js`). Each row shows five opacity swatches of the accent color.
The selected row has a left border in the accent color. Selecting an accent
updates `tempSettings.accent` and `tempSettings.accentColor` — the `App.jsx`
effect injects the corresponding CSS immediately so the color change is live.

#### Analysis

- **Default Time Range** — select (7 / 30 / 90 / 365 days). Controls the
  `?days=` parameter on Dashboard's `/activity` fetch.
- **Auto-analyze on paste** — toggle switch. When on, pasting a valid repo URL
  into the Home input fires the analysis immediately.
- **Email PR reviews** — toggle switch. When on, `PRReview` appends
  `?email=true` to the trigger POST so the report is mailed when it finishes.

Both toggles are `role="switch"` with `aria-checked` for accessibility.

#### AI Provider & Keys

Reads the current server config from `GET /config` (secrets masked as `"***"`)
and prefills the provider and model fields. The key inputs always start blank
(write-only — the server never returns the actual key value).

On "Save & Test Keys", the drawer calls `PUT /config` with only the **changed**
fields (empty key inputs are omitted — blank = "keep the stored value"):

```js
const payload = {};
if (provider changed)      payload.llm_provider = ...
if (model changed)         payload.llm_model = ...
if (local URL changed)     payload.local_llm_base_url = ...
if (api_key non-empty)     payload[KEY_FIELD[provider]] = ...
if (github_token non-empty) payload.github_token = ...
```

After saving, the drawer calls `GET /test` to verify which subsystems the new
keys actually enable, and surfaces the result in the feedback message (e.g.
`Saved to .env — LLM available, GitHub token configured`).

In **multiuser mode**, `PUT /config` returns `403` for secret fields — they
belong per-user in `/api/v1/me`. The drawer does not conditionally hide these
fields; the `403` response will surface as a `keysMessage` error.

#### About

A small card showing the API version and store backend read from `GET /health`
(soft-fail — shows "offline" if the backend is unreachable).

### Save Changes

Calls `saveSettings(tempSettings)` which writes to both React state and
`localStorage`. The accent and theme effects in `App.jsx` react immediately.

---

## `Card`

**File:** `src/components/Card.jsx`

```jsx
export default function Card({ children, className = "", ...props }) {
  return (
    <div
      className={`bg-surface-container border border-outline-variant/30 rounded-lg
                  overflow-hidden transition-all duration-200
                  hover:border-outline-variant/60 glow-card ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
```

A thin surface primitive — a rounded container with a subtle border, a hover
border brightening, and a `glow-card` class (defined in `index.css` as a
soft box-shadow in the primary color). Every page in the Developer Profile
view composes its bento grid from `Card` instances.

All extra props (`onClick`, `style`, ARIA attributes, etc.) are forwarded via
`...props`, so `Card` can be used as any block-level container without
needing a wrapper.

---

## `SyncBadge`

**File:** `src/components/SyncBadge.jsx`

**Purpose:** display how long ago a cached document was generated, and
optionally trigger a refresh.

### Props

| Prop | Type | Meaning |
|---|---|---|
| `timestamp` | ISO string | `generated_at` value from a report |
| `ageHours` | number | Pre-computed age in hours (from API `age_hours` field) |
| `stale` | boolean | Explicit stale flag from the API |
| `onRefresh` | function | If provided, renders as a `<button>` and calls this on click |

`ageHours` takes precedence over `timestamp` when both are provided. When
neither is given the badge renders "Synced" with no time.

### Staleness

If `stale` is not explicitly passed, it is inferred from the timestamp:
`diffHours > 24` → stale. A stale badge renders in `text-tertiary` (orange)
as a visual cue that the data may be outdated.

### Conditional rendering as button vs div

```jsx
const Comp = onRefresh ? "button" : "div";
return <Comp onClick={...} className={...}> ... </Comp>;
```

When `onRefresh` is provided the badge is interactive — clicking it fires the
refresh action. `e.stopPropagation()` prevents the click from bubbling to a
parent row or card link. When no `onRefresh` is provided it renders as a plain
`<div>`, non-interactive but still showing the age.

### Usage examples

```jsx
// Repo header — clicking re-analyzes
<SyncBadge timestamp={meta.generated_at} onRefresh={handleReAnalyze} />

// Home list row — display-only
<SyncBadge timestamp={lastActive} />

// Developer profile — uses API's pre-computed age
<SyncBadge ageHours={data.age_hours} stale={data.stale} onRefresh={handleBuildProfile} />
```
