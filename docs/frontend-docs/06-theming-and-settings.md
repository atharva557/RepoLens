# 06 — Theming & settings

Two modules handle all persistent UI preferences: `theme.js` owns the React
context and the CSS derivation logic; `settings.js` owns the localStorage
stores and helper functions. Neither has any side effects at import time.

---

## `src/lib/theme.js`

### `ThemeContext`

```js
export const ThemeContext = createContext(null);
```

Created here rather than in `App.jsx` to avoid a circular import: components
that import `ThemeContext` would transitively import `App.jsx`, which imports
those same components — this broke React fast-refresh. Keeping the context in
its own file breaks the cycle.

**Value shape** (set by `App.jsx`):

```js
{
  settings,                    // full global settings object (see settings.js)
  saveSettings,                // (newSettings) → updates state + localStorage
  theme,                       // "dark" | "light" | "system"
  setTheme,                    // (theme) → shorthand for saveSettings
}
```

Consumers that only need the accent color read `settings.accentColor` and
`settings.theme` from the context value. The most common consumer is the
heatmap color helper on `Dashboard` and `DeveloperProfile`:

```js
const { settings } = useContext(ThemeContext);
const color = getHeatmapColorStyle(count, settings.accentColor, settings.theme);
```

### `mixHex(a, b, t)`

```js
export function mixHex(a, b, t) {
  const pa = a.match(/\w\w/g).map((x) => parseInt(x, 16));
  const pb = b.match(/\w\w/g).map((x) => parseInt(x, 16));
  const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}
```

Linear interpolation between two hex colors. `t = 0` returns `a`; `t = 1`
returns `b`. Used exclusively by `accentThemeCss` to derive the accent's
companion tokens from the chosen primary color.

### `accentThemeCss(accent, color)`

Returns a CSS string that overrides the design-system palette for a non-default
accent. Returns `""` for `"amber"` (the default), so no `<style>` tag is
injected and the hand-tuned amber theme in `index.css` applies unchanged.

For all other accents the function derives a full palette family — not just
`--color-primary` — because the default amber theme has warm amber-tinted
borders (`--color-outline-variant: #554336`) and muted text
(`--color-on-surface-variant: #dbc2b0`). Switching only the primary would
leave the app looking "built for amber" regardless of accent.

**Dark mode derivation** (bare `:root`):

```
--color-primary                   → accent itself
--color-primary-container         → mix(accent, #000000, 0.45)   (dark container)
--color-on-primary                → mix(accent, #000000, 0.78)   (text on primary)
--color-on-primary-container      → mix(accent, #ffffff, 0.65)   (text on container)
--color-inverse-primary           → mix(accent, #000000, 0.35)
--color-outline                   → mix(accent, #8a8a8a,  0.55)  (accent-tinted border)
--color-outline-variant           → mix(accent, #262626,  0.72)  (subtle border)
--color-on-surface-variant        → mix(accent, #bdbdbd,  0.72)  (muted text)
```

**Light mode overrides** (`:root[data-theme="light"]`):

```
--color-primary                   → mix(accent, #000000, 0.3)    (darkened for contrast)
--color-on-primary                → #ffffff
--color-primary-container         → mix(accent, #ffffff, 0.7)
--color-on-primary-container      → mix(accent, #000000, 0.6)
--color-outline                   → #9ca3af                      (neutral gray restored)
--color-outline-variant           → #cccccc
--color-on-surface-variant        → #4b5563
```

In light mode borders and muted text revert to neutral grays because the warm
amber-tinted neutrals of the dark theme read poorly on a white background.

The generated `<style id="accent-theme">` tag is managed by `App.jsx`:
injected when accent ≠ amber, removed when it switches back to amber.

---

## `src/lib/settings.js`

Two independent localStorage stores: one per-repo (analysis parameters), one
global (UI preferences).

### Per-repo analysis settings

**Key format:** `repolens.settings.<repo-key>` (e.g.
`repolens.settings.pallets/flask`)

**Default shape:**

```js
export const DEFAULT_SETTINGS = {
  max_commits: undefined,   // undefined → full history
  top: 50,                  // hotspot rows returned
};
```

| Function | Behaviour |
|---|---|
| `loadRepoSettings(repo)` | Reads from localStorage, merges over `DEFAULT_SETTINGS`. Returns defaults for unknown repos or on parse failure. |
| `saveRepoSettings(repo, settings)` | Writes to localStorage. No-op if `repo` is falsy. Both functions swallow `localStorage` errors silently (private browsing / storage quota). |

These settings travel with every `POST /analyze` and `POST /commit-quality`
payload. They are loaded on `Home` submit, on `Dashboard` mount (for the
re-analyze flow), and in `Loading.handleRetry`.

### Global UI settings

**Key:** `repolens.global_settings`

**Default shape:**

```js
export const DEFAULT_GLOBAL_SETTINGS = {
  theme:           "dark",   // "dark" | "light" | "system"
  accent:          "amber",
  accentColor:     "#f5a524",
  timeRange:       "365",    // days for Dashboard activity window
  autoAnalyze:     false,    // auto-trigger on paste in Home
  autoEmailReview: false,    // ?email=true on PR review triggers
};
```

| Function | Behaviour |
|---|---|
| `loadGlobalSettings()` | Reads + parses localStorage. Applies legacy migration (see below). Merges over `DEFAULT_GLOBAL_SETTINGS`. |
| `saveGlobalSettings(settings)` | Serializes and writes to localStorage. Swallows errors silently. |

**Legacy migration:** older versions stored `contributionColor: "green" | "blue" | "orange" | "yellow"`.
`loadGlobalSettings` detects the old field and maps it to the new `accent` value:

```js
const LEGACY_ACCENT = { green: "jade", blue: "ocean", orange: "amber", yellow: "amber" };
if (!parsed.accent && parsed.contributionColor) {
  parsed.accent = LEGACY_ACCENT[parsed.contributionColor] || "amber";
}
```

The migration runs transparently on first load — no explicit migration step is
needed.

### Accent palette

```js
export const ACCENTS = [
  { name: "Amber",  value: "amber",  color: "#f5a524" },
  { name: "Jade",   value: "jade",   color: "#3fb950" },  // GitHub dark-theme green
  { name: "Ocean",  value: "ocean",  color: "#0ea5e9" },  // deep sky blue
  { name: "Orchid", value: "orchid", color: "#c084fc" },
];
```

`ACCENTS` is the single source of truth for the palette list. `SettingsDrawer`
renders it, `loadGlobalSettings` uses it to rehydrate `accentColor` from a
stored `accent` name (so renaming a color in the future only requires updating
`ACCENTS`).

### Color helpers

#### `hexToRgba(hex, opacity)`

Converts a 7-character hex color (`#rrggbb`) to an `rgba(r, g, b, opacity)`
string. Used for the heatmap to produce opacity variants of the accent:

```js
hexToRgba("#f5a524", 0.3)  // → "rgba(245, 165, 36, 0.3)"
```

#### `getHeatmapColorStyle(count, accentColor, theme)`

Returns the background color string for a single heatmap cell:

```js
// dark theme
if (!count)   return "#1e1e1c";           // empty cell
if (count ≤ 2) return rgba(accent, 0.30);
if (count ≤ 5) return rgba(accent, 0.55);
if (count ≤ 9) return rgba(accent, 0.80);
return accent;                             // full saturation

// light theme
if (!count)   return "#ebedf0";
if (count ≤ 2) return rgba(accent, 0.45);
if (count ≤ 5) return rgba(accent, 0.70);
if (count ≤ 9) return rgba(accent, 0.85);
return accent;
```

Light-mode cells start at higher opacity because the light background already
desaturates the color more than the dark background does.

`Dashboard` and `DeveloperProfile` wrap this in a local `getHeatmapStyle`
that additionally applies a `boxShadow` glow on cells with `count > 5`:

```js
const getHeatmapStyle = (count) => {
  const c = getHeatmapColorStyle(count, settings.accentColor, settings.theme);
  return count > 5
    ? { backgroundColor: c, boxShadow: `0 0 6px ${c}` }
    : { backgroundColor: c };
};
```

---

## How it all fits together

```
localStorage
  repolens.global_settings ──→ loadGlobalSettings()
                                     │
                               App.jsx useState(initializer)
                                     │
                             ThemeContext.Provider value={{ settings, ... }}
                                     │
                    ┌────────────────┴──────────────────────┐
                    │                                       │
              App.jsx effects                        Consumer components
          (inject data-theme attr,             (SettingsDrawer reads tempSettings,
           inject accent-theme <style>)         Dashboard/Profile use accentColor,
                                                Home checks autoAnalyze, etc.)
```

The flow is one-way: `loadGlobalSettings` → React state → context → components.
Mutations go through `saveSettings` (ThemeContext) → `saveGlobalSettings`
(localStorage) + `setSettings` (React state) in one atomic call, ensuring
the UI and storage are never out of sync.
