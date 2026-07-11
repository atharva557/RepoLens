// Theme context lives outside App.jsx so components can import it without
// pulling in the whole app (App <-> modal was a circular import, and a
// context export from App.jsx also breaks React fast-refresh).
import { createContext } from "react";

export const ThemeContext = createContext(null);

/** Mix two hex colors; t is the fraction of `b` (0..1). */
export function mixHex(a, b, t) {
  const pa = a.match(/\w\w/g).map((x) => parseInt(x, 16));
  const pb = b.match(/\w\w/g).map((x) => parseInt(x, 16));
  const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

/**
 * CSS overriding the *palette family* for a non-default accent.
 *
 * The default theme isn't just an amber primary — its borders
 * (--color-outline-variant #554336) and muted text (--color-on-surface-variant
 * #dbc2b0) are warm amber-tinted neutrals, so switching only --color-primary
 * left the app looking "built for amber". This derives the same relationships
 * from whichever accent is active, per theme:
 *
 *   dark  : accent primary + accent-tinted borders/muted text
 *   light : darkened accent for contrast on white, neutral grays restored
 *
 * `:root[data-theme=...]` rules out-rank the bare `:root` one, so the grey
 * theme keeps its own palette untouched.
 */
export function accentThemeCss(accent, color) {
  if (!accent || accent === "amber") return "";
  return `
:root {
  --color-primary: ${color};
  --color-primary-container: ${mixHex(color, "#000000", 0.45)};
  --color-on-primary: ${mixHex(color, "#000000", 0.78)};
  --color-on-primary-container: ${mixHex(color, "#ffffff", 0.65)};
  --color-inverse-primary: ${mixHex(color, "#000000", 0.35)};
  --color-outline: ${mixHex(color, "#8a8a8a", 0.55)};
  --color-outline-variant: ${mixHex(color, "#262626", 0.72)};
  --color-on-surface-variant: ${mixHex(color, "#bdbdbd", 0.72)};
}
:root[data-theme="light"] {
  --color-primary: ${mixHex(color, "#000000", 0.3)};
  --color-on-primary: #ffffff;
  --color-primary-container: ${mixHex(color, "#ffffff", 0.7)};
  --color-on-primary-container: ${mixHex(color, "#000000", 0.6)};
  --color-outline: #9ca3af;
  --color-outline-variant: #cccccc;
  --color-on-surface-variant: #4b5563;
}
`;
}
