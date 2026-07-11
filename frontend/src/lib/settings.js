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
