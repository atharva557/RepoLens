import { useContext, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ThemeContext } from "../lib/theme";
import { ACCENTS, hexToRgba } from "../lib/settings";
import { getJSON, putJSON } from "../lib/api";

// which write-only settings field carries each provider's key (PUT /config)
const KEY_FIELD = {
  openai: "openai_api_key",
  claude: "anthropic_api_key",
  gemini: "gemini_api_key",
};

/**
 * Right-hand settings drawer (from the design prototype): slides in over an
 * overlay, applies every change live, and persists through ThemeContext.
 *
 * Rendered through a portal: the navbar that opens it uses backdrop-blur, and
 * backdrop-filter turns an ancestor into the containing block for fixed
 * descendants — rendered in place, this drawer would be clipped to the header.
 */
export default function SettingsDrawer({ open, onClose }) {
  const { settings, saveSettings } = useContext(ThemeContext);
  const [about, setAbout] = useState(null);
  const [tempSettings, setTempSettings] = useState(settings);
  const [saveMessage, setSaveMessage] = useState("");

  // server-side keys section (PUT /config): masked reads, write-only inputs
  const [serverCfg, setServerCfg] = useState(null);
  const [keysForm, setKeysForm] = useState({
    llm_provider: "local", llm_model: "", local_llm_base_url: "",
    api_key: "", github_token: "",
  });
  const [keysSaving, setKeysSaving] = useState(false);
  const [keysMessage, setKeysMessage] = useState(null);

  // ESC closes; the page behind must not scroll while the drawer is open
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", handler);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  // Sync tempSettings when opened
  useEffect(() => {
    if (open) {
      setTempSettings(settings);
      setSaveMessage("");
    }
  }, [open, settings]);

  // live backend facts for the ABOUT card (soft-fail: the drawer must work
  // with the backend down)
  useEffect(() => {
    if (open && !about) {
      getJSON("/health").then(setAbout).catch(() => setAbout({ unavailable: true }));
    }
  }, [open, about]);

  // current server config (masked) whenever the drawer opens — provider and
  // model prefill from it; the secret inputs always start blank (write-only)
  useEffect(() => {
    if (!open) return;
    setKeysMessage(null);
    getJSON("/config")
      .then((cfg) => {
        setServerCfg(cfg);
        setKeysForm((prev) => ({
          ...prev,
          llm_provider: cfg.llm_provider || "local",
          llm_model: cfg.llm_model || "",
          local_llm_base_url: cfg.local_llm_base_url || "",
          api_key: "",
          github_token: "",
        }));
      })
      .catch(() => setServerCfg({ unavailable: true }));
  }, [open]);

  const set = (patch) => setTempSettings((prev) => ({ ...prev, ...patch }));
  const setKeys = (patch) => setKeysForm((prev) => ({ ...prev, ...patch }));

  const saveKeys = async () => {
    if (!serverCfg || serverCfg.unavailable) return;
    // only send what changed; blank secret inputs mean "keep the stored key"
    const payload = {};
    if (keysForm.llm_provider !== serverCfg.llm_provider) payload.llm_provider = keysForm.llm_provider;
    if (keysForm.llm_model !== (serverCfg.llm_model || "")) payload.llm_model = keysForm.llm_model;
    if (keysForm.llm_provider === "local" &&
        keysForm.local_llm_base_url !== (serverCfg.local_llm_base_url || "")) {
      payload.local_llm_base_url = keysForm.local_llm_base_url;
    }
    const keyField = KEY_FIELD[keysForm.llm_provider];
    if (keyField && keysForm.api_key.trim()) payload[keyField] = keysForm.api_key.trim();
    if (keysForm.github_token.trim()) payload.github_token = keysForm.github_token.trim();
    if (Object.keys(payload).length === 0) {
      setKeysMessage({ ok: false, text: "Nothing to save — fields are unchanged." });
      return;
    }
    setKeysSaving(true);
    setKeysMessage(null);
    try {
      const res = await putJSON("/config", payload);
      setServerCfg(res.config);
      setKeysForm((prev) => ({ ...prev, api_key: "", github_token: "" }));
      // verify live which subsystems the new settings actually light up
      let verdict = "";
      try {
        const t = await getJSON("/test");
        verdict = ` — LLM ${t.llm && t.llm.available ? "available" : "not available"}` +
                  `, GitHub token ${t.github_token ? "configured" : "missing"}`;
      } catch { /* the self-test is best-effort */ }
      setKeysMessage({ ok: true, text: `Saved${res.persisted ? " to .env" : " (in-memory only)"}${verdict}.` });
    } catch (e) {
      setKeysMessage({ ok: false, text: String(e.message || e) });
    } finally {
      setKeysSaving(false);
    }
  };

  const themeOptions = [
    { value: "system", label: "System" },
    { value: "dark", label: "Dark" },
    { value: "light", label: "Light" },
  ];

  return createPortal(
    <>
      {/* Overlay — opacity inline for the same token-collision reason as the
          drawer transform below */}
      <div
        style={{ opacity: open ? 1 : 0, transition: "opacity 300ms" }}
        className={`fixed inset-0 z-40 bg-black/45 backdrop-blur-[2px] ${open ? "" : "pointer-events-none"
          }`}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer */}
      <aside
        // the slide is driven by an inline transform: this codebase's custom
        // spacing tokens make several named Tailwind utilities resolve wrong
        // (see the max-w warning in index.css), and translate-x-0 lost the
        // same way — inline styles are immune
        style={{
          transform: open ? "translateX(0)" : "translateX(100%)",
          transition: "transform 220ms cubic-bezier(0.16, 1, 0.3, 1)",
        }}
        className="fixed right-0 top-0 h-full w-[380px] max-w-[90vw] bg-surface-container border-l border-outline-variant z-50 shadow-2xl overflow-hidden flex flex-col"
        role="dialog"
        aria-label="Settings"
        aria-hidden={!open}
      >
        {/* Header */}
        <div className="p-6 border-b border-outline-variant flex justify-between items-center">
          <div>
            <h2 className="font-heading-md text-heading-md text-primary">Settings</h2>
            <p className="text-label text-on-surface-variant">Personalize your dashboard</p>
          </div>
          <button
            className="p-2 hover:bg-surface-container-highest rounded text-on-surface-variant hover:text-on-surface transition-colors"
            onClick={onClose}
            aria-label="Close settings"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-8">
          {/* Appearance */}
          <div className="space-y-4">
            <p className="text-label text-on-surface-variant uppercase tracking-widest font-bold">
              {" APPEARANCE"}
            </p>
            <div className="flex p-1 bg-surface-container-lowest rounded border border-outline-variant">
              {themeOptions.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => set({ theme: opt.value })}
                  className={`flex-1 py-2 text-label rounded transition-all ${tempSettings.theme === opt.value
                    ? "bg-primary text-on-primary font-bold"
                    : "text-on-surface-variant hover:text-on-surface"
                    }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            <div className="space-y-3 pt-2">
              <p className="text-label text-on-surface-variant">Contribution Color Picker</p>
              <div className="space-y-2">
                {ACCENTS.map((a) => {
                  const selected = tempSettings.accent === a.value;
                  return (
                    <div
                      key={a.value}
                      role="button"
                      tabIndex={0}
                      aria-label={`Accent color: ${a.name}`}
                      aria-pressed={selected}
                      onClick={() => set({ accent: a.value, accentColor: a.color })}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          set({ accent: a.value, accentColor: a.color });
                        }
                      }}
                      className={`p-2 rounded cursor-pointer flex items-center justify-between transition-colors hover:bg-surface-container-low ${selected ? "bg-surface-container-high" : ""
                        }`}
                      style={selected ? { borderLeft: `3px solid ${a.color}` } : { borderLeft: "3px solid transparent" }}
                    >
                      <span className="text-label">{a.name}</span>
                      <div className="flex gap-1">
                        {[0.2, 0.4, 0.6, 0.8, 1].map((op) => (
                          <div
                            key={op}
                            className="w-4 h-4 rounded-[2px]"
                            style={{ backgroundColor: op === 1 ? a.color : hexToRgba(a.color, op) }}
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Analysis */}
          <div className="space-y-4 pt-4 border-t border-outline-variant">
            <p className="text-label text-on-surface-variant uppercase tracking-widest font-bold">
              {"ANALYSIS"}
            </p>
            <div className="space-y-4">
              <div className="space-y-2">
                <label className="text-label text-on-surface-variant" htmlFor="timeRangeSelect">
                  Default Time Range
                </label>
                <select
                  id="timeRangeSelect"
                  value={tempSettings.timeRange}
                  onChange={(e) => set({ timeRange: e.target.value })}
                  className="w-full bg-surface-container-lowest border border-outline-variant rounded px-3 py-2 text-body focus:outline-none focus:border-primary"
                >
                  <option value="7">Last 7 days</option>
                  <option value="30">Last 30 days</option>
                  <option value="90">Last 90 days</option>
                  <option value="365">Last 1 year</option>
                </select>
              </div>

              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <p className="text-body font-medium">Auto-analyze on paste</p>
                  <p className="text-label text-on-surface-variant">
                    Trigger analysis when repository URL is detected
                  </p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={tempSettings.autoAnalyze}
                  aria-label="Auto-analyze on paste"
                  onClick={() => set({ autoAnalyze: !tempSettings.autoAnalyze })}
                  className={`relative w-10 h-5 rounded-full transition-colors flex-shrink-0 ${tempSettings.autoAnalyze ? "bg-primary/30" : "bg-surface-container-highest"
                    }`}
                >
                  <span
                    className={`absolute top-1 w-3 h-3 rounded-full transition-all duration-200 ${tempSettings.autoAnalyze ? "left-6 bg-primary" : "left-1 bg-on-surface-variant"
                      }`}
                  />
                </button>
              </div>
            </div>
          </div>

          {/* AI provider & keys — server-side (PUT /config): applied live,
              persisted to .env; secrets are write-only and never echoed */}
          <div className="space-y-4 pt-4 border-t border-outline-variant">
            <p className="text-label text-on-surface-variant uppercase tracking-widest font-bold">
              {"AI PROVIDER & KEYS"}
            </p>
            {serverCfg?.unavailable ? (
              <p className="text-label text-on-surface-variant">
                Backend offline — start the API server to manage keys.
              </p>
            ) : !serverCfg ? (
              <p className="text-label text-on-surface-variant">Loading current configuration…</p>
            ) : (
              <div className="space-y-4">
                <div className="space-y-2">
                  <label className="text-label text-on-surface-variant" htmlFor="llmProviderSelect">
                    AI Provider
                  </label>
                  <select
                    id="llmProviderSelect"
                    value={keysForm.llm_provider}
                    onChange={(e) => setKeys({ llm_provider: e.target.value })}
                    className="w-full bg-surface-container-lowest border border-outline-variant rounded px-3 py-2 text-body focus:outline-none focus:border-primary"
                  >
                    <option value="local">Local (LM Studio)</option>
                    <option value="claude">Claude (Anthropic)</option>
                    <option value="openai">OpenAI</option>
                    <option value="gemini">Gemini (Google)</option>
                  </select>
                </div>

                {keysForm.llm_provider === "local" ? (
                  <div className="space-y-2">
                    <label className="text-label text-on-surface-variant" htmlFor="localLlmUrl">
                      Local Server URL
                    </label>
                    <input
                      id="localLlmUrl"
                      type="text"
                      value={keysForm.local_llm_base_url}
                      onChange={(e) => setKeys({ local_llm_base_url: e.target.value })}
                      placeholder="http://localhost:1234/v1"
                      className="w-full bg-surface-container-lowest border border-outline-variant rounded px-3 py-2 text-body font-code focus:outline-none focus:border-primary placeholder:text-on-surface-variant/40"
                    />
                  </div>
                ) : (
                  <div className="space-y-2">
                    <label className="text-label text-on-surface-variant flex items-center justify-between" htmlFor="llmApiKey">
                      <span>API Key</span>
                      {serverCfg[KEY_FIELD[keysForm.llm_provider]] === "***" && (
                        <span className="text-green-500 font-code text-[10px]">configured ✓</span>
                      )}
                    </label>
                    <input
                      id="llmApiKey"
                      type="password"
                      autoComplete="off"
                      value={keysForm.api_key}
                      onChange={(e) => setKeys({ api_key: e.target.value })}
                      placeholder={serverCfg[KEY_FIELD[keysForm.llm_provider]] === "***"
                        ? "•••• configured — paste to replace"
                        : "paste your API key"}
                      className="w-full bg-surface-container-lowest border border-outline-variant rounded px-3 py-2 text-body font-code focus:outline-none focus:border-primary placeholder:text-on-surface-variant/40"
                    />
                  </div>
                )}

                <div className="space-y-2">
                  <label className="text-label text-on-surface-variant" htmlFor="llmModel">
                    Model <span className="text-on-surface-variant/60">(optional)</span>
                  </label>
                  <input
                    id="llmModel"
                    type="text"
                    value={keysForm.llm_model}
                    onChange={(e) => setKeys({ llm_model: e.target.value })}
                    placeholder="provider default"
                    className="w-full bg-surface-container-lowest border border-outline-variant rounded px-3 py-2 text-body font-code focus:outline-none focus:border-primary placeholder:text-on-surface-variant/40"
                  />
                </div>

                <div className="space-y-2 pt-2">
                  <label className="text-label text-on-surface-variant flex items-center justify-between" htmlFor="githubToken">
                    <span>GitHub Token</span>
                    {serverCfg.github_token === "***" && (
                      <span className="text-green-500 font-code text-[10px]">configured ✓</span>
                    )}
                  </label>
                  <input
                    id="githubToken"
                    type="password"
                    autoComplete="off"
                    value={keysForm.github_token}
                    onChange={(e) => setKeys({ github_token: e.target.value })}
                    placeholder={serverCfg.github_token === "***"
                      ? "•••• configured — paste to replace"
                      : "ghp_… or github_pat_…"}
                    className="w-full bg-surface-container-lowest border border-outline-variant rounded px-3 py-2 text-body font-code focus:outline-none focus:border-primary placeholder:text-on-surface-variant/40"
                  />
                  <p className="text-[10px] text-on-surface-variant leading-relaxed">
                    Powers developer profiles, PR reviews (and optional PR comments),
                    the repo header metadata, and the recent-PRs card — and raises the
                    GitHub rate limit from 60 to 5,000 req/h. Hotspot and commit-quality
                    analysis of public repos works without it.
                  </p>
                </div>

                {keysMessage && (
                  <div className={`p-2 text-label rounded text-center border ${keysMessage.ok
                    ? "bg-green-500/10 text-green-500 border-green-500/20"
                    : "bg-red-500/10 text-red-400 border-red-500/20"}`}>
                    {keysMessage.text}
                  </div>
                )}
                <button
                  onClick={saveKeys}
                  disabled={keysSaving}
                  className="w-full border border-primary/60 text-primary py-2.5 font-bold rounded hover:bg-primary/10 transition-colors uppercase tracking-widest text-label disabled:opacity-50"
                >
                  {keysSaving ? "Saving & testing…" : "Save & Test Keys"}
                </button>
              </div>
            )}
          </div>

          {/* About */}
          <div className="space-y-4 pt-4 border-t border-outline-variant">
            <p className="text-label text-on-surface-variant uppercase tracking-widest font-bold">
              {"ABOUT"}
            </p>
            <div className="p-4 rounded bg-surface-container-lowest border border-outline-variant space-y-2">
              <div className="flex justify-between text-label">
                <span className="text-on-surface-variant">Version</span>
                <span className="font-code">
                  {about?.version ? `v${about.version}` : about?.unavailable ? "offline" : "…"}
                </span>
              </div>
              <div className="flex justify-between text-label">
                <span className="text-on-surface-variant">Store</span>
                <span className="font-code uppercase">
                  {about?.store || (about?.unavailable ? "unreachable" : "…")}
                </span>
              </div>
              <p className="text-[10px] text-on-surface-variant pt-2">
                RepoLens — GitHub analytics &amp; intelligence. Full diagnostics at /status.
              </p>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-6 bg-surface-container-high border-t border-outline-variant">
          {saveMessage && (
            <div className="mb-4 p-2 bg-green-500/10 text-green-500 text-label rounded text-center border border-green-500/20">
              {saveMessage}
            </div>
          )}
          <button
            onClick={() => {
              saveSettings(tempSettings);
              setSaveMessage("Settings saved successfully.");
              setTimeout(() => setSaveMessage(""), 3000);
            }}
            className="w-full bg-primary text-on-primary py-3 font-bold rounded hover:opacity-90 transition-opacity uppercase tracking-widest text-label glow-primary"
          >
            Save Changes
          </button>
        </div>
      </aside>
    </>,
    document.body
  );
}
