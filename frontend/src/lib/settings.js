// Per-repo analysis settings + global UI settings, both localStorage-backed.

export const DEFAULT_SETTINGS = {
  max_commits: undefined,
  top: 50,
};

export function loadRepoSettings(repo) {
  if (!repo) return { ...DEFAULT_SETTINGS };
  try {
    const saved = localStorage.getItem(`repolens.settings.${repo}`);
    if (saved) {
      const parsed = JSON.parse(saved);
      return { ...DEFAULT_SETTINGS, ...parsed };
    }
  } catch {
    // ignore
  }
  return { ...DEFAULT_SETTINGS };
}

export function saveRepoSettings(repo, settings) {
  if (!repo) return;
  try {
    localStorage.setItem(`repolens.settings.${repo}`, JSON.stringify(settings));
  } catch {
    // ignore
  }
}

/* ------------------------------------------------------------------ */
/* Global UI settings (settings drawer)                                */
/* ------------------------------------------------------------------ */

// Accent palette from the design prototype. "amber" is the app's default
// primary token, so choosing it means "no override".
export const ACCENTS = [
  { name: "Amber", value: "amber", color: "#f5a524" },
  { name: "Jade", value: "jade", color: "#3fb950" },   // GitHub's dark-theme green
  { name: "Ocean", value: "ocean", color: "#0ea5e9" }, // deeper sky than the old #38bdf8
  { name: "Orchid", value: "orchid", color: "#c084fc" },
];

export const DEFAULT_GLOBAL_SETTINGS = {
  theme: "dark", // dark | light | system
  accent: "amber",
  accentColor: "#f5a524",
  timeRange: "365", // dashboard activity window, in days
  autoAnalyze: false, // auto-run analysis when a GitHub URL is pasted on Home
};

// pre-drawer versions stored contributionColor: green|blue|orange|yellow
const LEGACY_ACCENT = { green: "jade", blue: "ocean", orange: "amber", yellow: "amber" };

export function loadGlobalSettings() {
  try {
    const saved = localStorage.getItem("repolens.global_settings");
    if (saved) {
      const parsed = JSON.parse(saved);
      if (!parsed.accent && parsed.contributionColor) {
        parsed.accent = LEGACY_ACCENT[parsed.contributionColor] || "amber";
      }
      const known = ACCENTS.find((a) => a.value === parsed.accent);
      if (known) parsed.accentColor = known.color;
      return { ...DEFAULT_GLOBAL_SETTINGS, ...parsed };
    }
  } catch {
    // ignore
  }
  return { ...DEFAULT_GLOBAL_SETTINGS };
}

export function saveGlobalSettings(settings) {
  try {
    localStorage.setItem("repolens.global_settings", JSON.stringify(settings));
  } catch {
    // ignore
  }
}

export function hexToRgba(hex, opacity) {
  let r = 0, g = 0, b = 0;
  if (hex && hex.length === 7) {
    r = parseInt(hex.substring(1, 3), 16);
    g = parseInt(hex.substring(3, 5), 16);
    b = parseInt(hex.substring(5, 7), 16);
  }
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

export function getHeatmapColorStyle(count, accentColor, theme) {
  const isLight = theme === "light";
  if (!count) return isLight ? "#ebedf0" : "#1e1e1c";
  const accent = accentColor || DEFAULT_GLOBAL_SETTINGS.accentColor;
  
  if (isLight) {
    if (count <= 2) return hexToRgba(accent, 0.45);
    if (count <= 5) return hexToRgba(accent, 0.7);
    if (count <= 9) return hexToRgba(accent, 0.85);
    return accent;
  }
  
  if (count <= 2) return hexToRgba(accent, 0.3);
  if (count <= 5) return hexToRgba(accent, 0.55);
  if (count <= 9) return hexToRgba(accent, 0.8);
  return accent;
}
