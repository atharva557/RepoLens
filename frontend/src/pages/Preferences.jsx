import { useContext, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ThemeContext } from "../lib/theme";
import { ACCENTS } from "../lib/settings";

// ─── Design tokens ────────────────────────────────────────────────────────────
const BLUE = "#00C8FF";
const BLUE_GLOW = "rgba(0,200,255,0.40)";
const PANEL_BG = "#111318";
const BORDER = "rgba(255,255,255,0.08)";

const SWATCHES = {
  amber: ["#6b4000", "#a86200", "#d48200", "#f0a800", "#f5c842"],
  jade: ["#0a3320", "#0f6030", "#159045", "#1ab855", "#2ee86a"],
  ocean: ["#062535", "#0a4a6e", "#0f72a8", "#14a0d8", "#2ac8f0"],
  orchid: ["#2a1040", "#52189a", "#7830c8", "#a050e8", "#c87af8"],
};

// vivid tip of each palette — used for button glow when that accent is active
const ACCENT_VIVID = {
  amber: "#f5a524",
  jade: "#3fb950",
  ocean: "#0ea5e9",
  orchid: "#c084fc",
};

// pre-computed rgba glow strings per accent
const ACCENT_GLOW = {
  amber: "rgba(245,165,36,0.45)",
  jade: "rgba(63,185,80,0.45)",
  ocean: "rgba(14,165,233,0.45)",
  orchid: "rgba(192,132,252,0.45)",
};

// ─── sub-components ───────────────────────────────────────────────────────────

function ThemeSegment({ value, onChange, savedColor }) {
  const opts = [
    { v: "system", l: "System" },
    { v: "dark", l: "Dark" },
    { v: "light", l: "Light" },
  ];
  return (
    <div style={{
      display: "flex",
      background: "#0a0d14",
      border: `1px solid ${BORDER}`,
      borderRadius: "10px",
      padding: "4px",
      gap: "3px",
    }}>
      {opts.map(({ v, l }) => {
        const on = value === v;
        return (
          <button
            key={v}
            type="button"
            onClick={() => onChange(v)}
            aria-pressed={on}
            style={{
              flex: 1,
              padding: "10px 0",
              borderRadius: "7px",
              fontSize: "12px",
              fontWeight: on ? 700 : 400,
              cursor: "pointer",
              border: "none",
              outline: "none",
              background: on ? savedColor : "transparent",
              color: on ? "#000" : "rgba(255,255,255,0.40)",
              transition: "background 180ms ease, color 180ms ease",
              letterSpacing: on ? "0.01em" : "normal",
            }}
          >
            {l}
          </button>
        );
      })}
    </div>
  );
}

function ColorRow({ accent, selected, onSelect, savedColor }) {
  const swatches = SWATCHES[accent.value] || [];
  return (
    <button
      type="button"
      onClick={() => onSelect(accent)}
      aria-pressed={selected}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        width: "100%",
        padding: "14px 16px",
        borderRadius: "8px",
        cursor: "pointer",
        border: "none",
        outline: "none",
        background: selected ? "rgba(255,255,255,0.06)" : "transparent",
        borderLeft: selected ? `3px solid ${savedColor}` : "3px solid transparent",
        transition: "background 150ms ease",
        textAlign: "left",
        boxSizing: "border-box",
      }}
    >
      <span style={{
        fontSize: "13px",
        color: selected ? "#fff" : "rgba(255,255,255,0.65)",
        fontWeight: selected ? 600 : 400,
      }}>
        {accent.name}
      </span>
      <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
        {swatches.map((color, i) => (
          <span
            key={i}
            style={{
              width: "26px",
              height: "26px",
              borderRadius: "5px",
              background: color,
              display: "block",
              flexShrink: 0,
            }}
          />
        ))}
      </div>
    </button>
  );
}

// ─── page ─────────────────────────────────────────────────────────────────────

export default function Preferences() {
  const navigate = useNavigate();
  const { settings, saveSettings } = useContext(ThemeContext);

  const [draft, setDraft] = useState({
    theme: settings.theme || "dark",
    accent: settings.accent,
    accentColor: settings.accentColor,
  });
  const [saved, setSaved] = useState(false);
  const [savedAccent, setSavedAccent] = useState(null); // null = use default blue

  const savedColor = ACCENT_VIVID[settings.accent] || BLUE;
  const savedGlow = ACCENT_GLOW[settings.accent] || BLUE_GLOW;

  function handleSave() {
    saveSettings({ ...settings, ...draft });
    setSavedAccent(draft.accent);
    setSaved(true);
    setTimeout(() => {
      setSaved(false);
      // redirect back to the page from which the user accessed preferences
      if (window.history.length > 1) {
        navigate(-1);
      } else {
        navigate("/");
      }
    }, 600);
  }

  return (
    <>
      {/* Dark backdrop */}
      <div
        onClick={() => navigate(-1)}
        style={{
          position: "fixed", inset: 0,
          background: "rgba(0,0,0,0.60)",
          backdropFilter: "blur(2px)",
          zIndex: 40,
        }}
      />

      {/* Right-side panel */}
      <aside
        role="dialog"
        aria-label="Preferences"
        style={{
          position: "fixed", right: 0, top: 0, bottom: 0,
          width: "400px", maxWidth: "92vw",
          background: PANEL_BG,
          borderLeft: `1px solid ${BORDER}`,
          boxShadow: "-10px 0 50px rgba(0,0,0,0.6)",
          zIndex: 50,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >

        {/* ── Header ───────────────────────────────────────────────────── */}
        <div style={{ padding: "26px 24px 0", flexShrink: 0 }}>
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
            <div>
              <h2 style={{ fontSize: "19px", fontWeight: 700, color: savedColor, margin: 0, lineHeight: 1.2, transition: "color 250ms ease" }}>
                Preferences
              </h2>
              <p style={{ fontSize: "12px", color: "rgba(255,255,255,0.35)", margin: "4px 0 0" }}>
                Personalize your dashboard
              </p>
            </div>
            <button
              type="button"
              onClick={() => navigate(-1)}
              aria-label="Close"
              style={{
                background: "none", border: "none",
                color: "rgba(255,255,255,0.45)",
                fontSize: "24px", cursor: "pointer",
                padding: "0", lineHeight: 1,
                transition: "color 150ms ease",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = "#fff")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(255,255,255,0.45)")}
            >
              ×
            </button>
          </div>
          {/* Divider */}
          <div style={{ height: "1px", background: BORDER, margin: "20px 0 0" }} />
        </div>

        {/* ── Scrollable body ───────────────────────────────────────────── */}
        <div style={{ flex: 1, overflowY: "auto", padding: "24px 24px 0" }}>

          {/* APPEARANCE label */}
          <p style={{
            fontSize: "10px", fontWeight: 700,
            letterSpacing: "0.12em", textTransform: "uppercase",
            color: "rgba(255,255,255,0.30)",
            marginBottom: "14px",
          }}>
            Appearance
          </p>

          {/* System / Dark / Light */}
          <ThemeSegment
            value={draft.theme}
            onChange={(t) => setDraft((d) => ({ ...d, theme: t }))}
            savedColor={savedColor}
          />

          {/* Contribution Color Picker */}
          <p style={{
            fontSize: "12px", fontWeight: 400,
            color: "rgba(255,255,255,0.40)",
            margin: "24px 0 10px",
          }}>
            Contribution Color Picker
          </p>

          <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
            {ACCENTS.map((accent) => (
              <ColorRow
                key={accent.value}
                accent={accent}
                selected={draft.accent === accent.value}
                onSelect={(a) => setDraft((d) => ({ ...d, accent: a.value, accentColor: a.color }))}
                savedColor={savedColor}
              />
            ))}
          </div>

        </div>

        {/* ── Fixed footer — Save Changes ───────────────────────────────── */}
        <div style={{
          padding: "16px 24px 24px",
          flexShrink: 0,
          background: PANEL_BG,
        }}>
          <button
            type="button"
            onClick={handleSave}
            style={{
              width: "100%",
              padding: "14px",
              borderRadius: "10px",
              border: "none",
              background: saved ? (ACCENT_VIVID[savedAccent] || "#00e6b3") : savedColor,
              color: "#000",
              fontSize: "12px",
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              cursor: "pointer",
              boxShadow: `0 0 22px ${saved ? (ACCENT_GLOW[savedAccent] || BLUE_GLOW) : savedGlow}, 0 0 8px ${saved ? (ACCENT_GLOW[savedAccent] || BLUE_GLOW) : savedGlow}`,
              transition: "background 250ms ease, box-shadow 250ms ease",
            }}
          >
            {saved ? "Saved" : "Save Changes"}
          </button>
        </div>

      </aside>
    </>
  );
}
