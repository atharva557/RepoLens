# 02 — App shell & routing

## Entry point (`main.jsx`)

```jsx
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

`StrictMode` is on in development — effects and renders run twice to surface
side-effect bugs. Nothing in the app breaks under double-invocation.

## `App.jsx` — the provider stack

`App` owns three concerns: theme state, the context providers, and layout. It
renders no page content itself.

### Provider nesting order

```
ThemeContext.Provider          (theme + accent + saveSettings)
  └── AuthProvider             (session mode + user object)
        └── BrowserRouter
              ├── Navbar       (fixed top bar — always visible)
              └── div.pt-[52px]
                    └── Gate  (route tree or Login wall)
```

The 52 px top padding on the content wrapper offsets the fixed `Navbar`
(`h-[52px]`), so page content never slides under it.

### Theme state

```js
const [settings, setSettings] = useState(() => loadGlobalSettings());
```

`settings` is loaded from `localStorage` on first render via the initializer
function (runs once, never on re-render). It holds:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `theme` | `"dark" \| "light" \| "system"` | `"dark"` | Color scheme |
| `accent` | string | `"amber"` | Active accent name |
| `accentColor` | hex string | `"#f5a524"` | Hex color for the accent |
| `timeRange` | string (days) | `"365"` | Dashboard activity window |
| `autoAnalyze` | boolean | `false` | Auto-trigger on paste in Home |
| `autoEmailReview` | boolean | `false` | Email PR report on finish |

### Theme application (dark / light / system)

```js
useEffect(() => {
  const apply = () => {
    const resolved = theme === "system"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
      : theme;
    if (resolved === "dark") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = resolved;
    }
  };
  apply();
  if (settings.theme === "system") {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }
}, [settings.theme]);
```

- **Dark** (default): `data-theme` attribute is absent. Tailwind/CSS custom
  property rules under `:root` apply.
- **Light**: `data-theme="light"` is set. Rules under `:root[data-theme="light"]`
  override the defaults.
- **System**: The OS preference is resolved immediately, and a `MediaQueryList`
  listener keeps it live — switching the OS to light mode while the app is
  open re-applies without a reload.

### Accent application

```js
useEffect(() => {
  let tag = document.getElementById("accent-theme");
  const css = accentThemeCss(settings.accent, settings.accentColor);
  if (!css) {
    if (tag) tag.remove();
    return;
  }
  if (!tag) {
    tag = document.createElement("style");
    tag.id = "accent-theme";
    document.head.appendChild(tag);
  }
  tag.textContent = css;
}, [settings.accent, settings.accentColor]);
```

For the default `"amber"` accent, `accentThemeCss` returns `""` and no
`<style>` tag is injected — the hand-tuned amber palette in `index.css`
applies as-is. For any other accent, a `<style id="accent-theme">` is written
into `<head>` with `:root` overrides for `--color-primary` and its derived
tokens. See [06-theming-and-settings.md](06-theming-and-settings.md) for the
full derivation logic.

### `ThemeContext` value

```js
<ThemeContext.Provider value={{
  settings,
  saveSettings,
  theme: settings.theme,
  setTheme: (newTheme) => saveSettings({ ...settings, theme: newTheme })
}}>
```

Any component that needs the current accent color or theme reads from
`ThemeContext`. The most common consumer is the heatmap color helper
(`getHeatmapColorStyle`) which needs `accentColor` and `theme` to pick the
right shade.

`saveSettings` calls `setSettings` (React state) and `saveGlobalSettings`
(localStorage) in one shot, so the UI updates immediately and the change
survives a page refresh.

---

## `Gate` — the auth wall

```jsx
function Gate() {
  const { mode, user } = useContext(AuthContext);
  if (mode === "loading") return null;
  if (mode === "multiuser" && !user) return <Login />;
  return (
    <Routes>
      <Route path="/"          element={<Home />} />
      <Route path="/loading"   element={<Loading />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/hotspots"  element={<BugHotspots />} />
      <Route path="/profile"   element={<DeveloperProfile />} />
      <Route path="/pr-review" element={<PRReview />} />
      <Route path="/status"    element={<Status />} />
    </Routes>
  );
}
```

`Gate` has three render outcomes:

| `mode` | `user` | Renders |
|---|---|---|
| `"loading"` | any | `null` — suppresses a flash while the `/me` probe is in-flight |
| `"single"` | `null` | Full route tree — single-user mode, no wall |
| `"multiuser"` | `null` | `<Login />` — anonymous visitor, shown on every URL |
| `"multiuser"` | object | Full route tree — authenticated user |

`Login` has **no route** of its own. It replaces the entire route tree for
anonymous visitors, which means the URL the user asked for (`/dashboard?repo=...`)
is preserved in the browser bar — once they sign in, `AuthContext.refresh()`
re-probes `/me`, `mode` flips to `multiuser` with a user, `Gate` re-renders,
and `BrowserRouter` delivers the originally requested route.

---

## Route table

| Path | Page component | Purpose |
|---|---|---|
| `/` | `Home` | Entry point, repo input, recent analyses, profile chips |
| `/loading` | `Loading` | Job polling with progress bar; redirects on completion |
| `/dashboard` | `Dashboard` | Full repo overview — heatmap, contributors, insights, quality, PRs |
| `/hotspots` | `BugHotspots` | Ranked hotspot table with side-panel detail view |
| `/profile` | `DeveloperProfile` | Developer stats, contribution heatmap, AI summary |
| `/pr-review` | `PRReview` | PR risk report — input screen or full report view |
| `/status` | `Status` | Raw JSON dump of `GET /test` and `GET /config` |

All routes that need a specific repository receive it via the `repo` query
parameter (`?repo=owner/repo`). `Navbar` propagates the current `repo` param
to every context-aware link so it is never lost during navigation.
