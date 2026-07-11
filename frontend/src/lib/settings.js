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
  } catch (e) {
    // ignore
  }
  return { ...DEFAULT_SETTINGS };
}

export function saveRepoSettings(repo, settings) {
  if (!repo) return;
  try {
    localStorage.setItem(`repolens.settings.${repo}`, JSON.stringify(settings));
  } catch (e) {
    // ignore
  }
}

export const DEFAULT_GLOBAL_SETTINGS = {
  theme: "dark",
  contributionColor: "orange",
};

export function loadGlobalSettings() {
  try {
    const saved = localStorage.getItem("repolens.global_settings");
    if (saved) {
      return { ...DEFAULT_GLOBAL_SETTINGS, ...JSON.parse(saved) };
    }
  } catch (e) {
    // ignore
  }
  return { ...DEFAULT_GLOBAL_SETTINGS };
}

export function saveGlobalSettings(settings) {
  try {
    localStorage.setItem("repolens.global_settings", JSON.stringify(settings));
  } catch (e) {
    // ignore
  }
}

export function getHeatmapColorStyle(count, colorName, theme) {
  const isLight = theme === "light";
  
  if (count === 0) {
    return isLight ? "#e5e7eb" : "#2a2a2a";
  }

  const colorMap = {
    green: {
      light: ["#bbf7d0", "#86efac", "#22c55e", "#15803d"],
      dark: ["#14532d", "#166534", "#15803d", "#22c55e"]
    },
    blue: {
      light: ["#bfdbfe", "#93c5fd", "#3b82f6", "#1d4ed8"],
      dark: ["#1e3a8a", "#1e40af", "#1d4ed8", "#3b82f6"]
    },
    orange: {
      light: ["#fed7aa", "#fdba74", "#f97316", "#c2410c"],
      dark: ["#7c2d12", "#9a3412", "#c2410c", "#f97316"]
    },
    yellow: {
      light: ["#fef08a", "#fde047", "#eab308", "#a16207"],
      dark: ["#713f12", "#854d0e", "#a16207", "#eab308"]
    }
  };

  const palette = colorMap[colorName] || colorMap.orange;
  const shades = isLight ? palette.light : palette.dark;

  if (count <= 2) return shades[0];
  if (count <= 5) return shades[1];
  if (count <= 9) return shades[2];
  return shades[3];
}

