import { useContext, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ThemeContext } from "../lib/theme";
import { getJSON, putJSON } from "../lib/api";

const KEY_FIELD = {
  openai: "openai_api_key",
  claude:  "anthropic_api_key",
  gemini:  "gemini_api_key",
};

const inputCls = "w-full bg-surface-container-lowest border border-outline-variant rounded-lg px-3 py-2 text-[13px] text-on-surface focus:outline-none focus:border-primary transition-colors";

function SectionHeader({ children }) {
  return (
    <div className="flex items-center gap-3 mb-5">
      <span className="w-[3px] h-4 rounded-full bg-primary shrink-0" />
      <p className="text-[10px] uppercase tracking-[0.12em] font-bold text-on-surface-variant m-0">
        {children}
      </p>
    </div>
  );
}

function Toggle({ checked, onChange, id, label, description }) {
  return (
    <div className="flex items-center justify-between py-1">
      <div>
        <p className="text-[13px] font-medium text-on-surface m-0">{label}</p>
        {description && (
          <p className="text-[11px] text-on-surface-variant mt-1 m-0">{description}</p>
        )}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative w-10 h-5 rounded-full transition-colors duration-200 flex-shrink-0 ml-6 ${checked ? "bg-primary" : "bg-outline-variant"}`}
      >
        <span
          className={`absolute top-[2px] w-4 h-4 rounded-full bg-surface transition-all duration-200 ${checked ? "left-[22px]" : "left-[2px]"}`}
        />
      </button>
    </div>
  );
}

export default function Settings() {
  const navigate = useNavigate();
  const { settings, saveSettings } = useContext(ThemeContext);
  const [tempSettings, setTempSettings] = useState(settings);
  const [saveMsg, setSaveMsg] = useState("");

  const [serverCfg, setServerCfg] = useState(null);
  const [keysForm, setKeysForm]   = useState({
    llm_provider: "local", llm_model: "", local_llm_base_url: "", api_key: "", github_token: "",
  });
  const [keysSaving, setKeysSaving] = useState(false);
  const [keysMsg, setKeysMsg]       = useState(null);
  const [about, setAbout]           = useState(null);

  useEffect(() => {
    getJSON("/config")
      .then((cfg) => {
        setServerCfg(cfg);
        setKeysForm((p) => ({
          ...p,
          llm_provider:       cfg.llm_provider       || "local",
          llm_model:          cfg.llm_model           || "",
          local_llm_base_url: cfg.local_llm_base_url  || "",
          api_key: "", github_token: "",
        }));
      })
      .catch(() => setServerCfg({ unavailable: true }));

    getJSON("/health").then(setAbout).catch(() => setAbout({ unavailable: true }));
  }, []);

  const set     = (patch) => setTempSettings((p) => ({ ...p, ...patch }));
  const setKeys = (patch) => setKeysForm((p) => ({ ...p, ...patch }));

  function handleSave() {
    saveSettings(tempSettings);
    setSaveMsg("Settings saved.");
    setTimeout(() => {
      setSaveMsg("");
      if (window.history.length > 1) navigate(-1);
      else navigate("/");
    }, 600);
  }

  async function saveKeys() {
    if (!serverCfg || serverCfg.unavailable) return;
    const payload = {};
    if (keysForm.llm_provider !== serverCfg.llm_provider) payload.llm_provider = keysForm.llm_provider;
    if (keysForm.llm_model !== (serverCfg.llm_model || "")) payload.llm_model = keysForm.llm_model;
    if (keysForm.llm_provider === "local" && keysForm.local_llm_base_url !== (serverCfg.local_llm_base_url || ""))
      payload.local_llm_base_url = keysForm.local_llm_base_url;
    const keyField = KEY_FIELD[keysForm.llm_provider];
    if (keyField && keysForm.api_key.trim()) payload[keyField] = keysForm.api_key.trim();
    if (keysForm.github_token.trim()) payload.github_token = keysForm.github_token.trim();

    if (Object.keys(payload).length === 0) {
      setKeysMsg({ ok: false, text: "Nothing to save — fields are unchanged." });
      return;
    }
    setKeysSaving(true); setKeysMsg(null);
    try {
      const res = await putJSON("/config", payload);
      setServerCfg(res.config);
      setKeysForm((p) => ({ ...p, api_key: "", github_token: "" }));
      let verdict = "";
      try {
        const t = await getJSON("/test");
        verdict = ` — LLM ${t.llm?.available ? "available" : "not available"}, GitHub ${t.github_token ? "configured" : "missing"}`;
      } catch { /* best-effort */ }
      setKeysMsg({ ok: true, text: `Saved${res.persisted ? " to .env" : " (in-memory)"}${verdict}.` });
    } catch (e) {
      setKeysMsg({ ok: false, text: String(e.message || e) });
    } finally {
      setKeysSaving(false);
    }
  }

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={() => {
          if (window.history.length > 1) {
            navigate(-1);
          } else {
            navigate("/");
          }
        }}
        className="fixed inset-0 bg-black/20 backdrop-blur-md z-40 transition-colors"
      />

      {/* Right-side panel */}
      <aside
        role="dialog"
        aria-label="Settings"
        className="fixed right-0 top-0 bottom-0 w-[400px] max-w-[92vw] bg-surface-container border-l border-outline-variant shadow-2xl z-50 flex flex-col overflow-hidden transition-colors"
      >
        {/* ── Header ───────────────────────────────────────────────────── */}
        <div className="px-6 pt-6 shrink-0">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-[19px] font-bold text-primary m-0 leading-tight transition-colors duration-250">
                Settings
              </h2>
              <p className="text-[12px] text-on-surface-variant mt-1">
                Configure analysis defaults &amp; keys
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                if (window.history.length > 1) {
                  navigate(-1);
                } else {
                  navigate("/");
                }
              }}
              aria-label="Close"
              className="bg-transparent border-none text-on-surface-variant text-[24px] cursor-pointer p-0 leading-none transition-colors duration-150 hover:text-on-surface"
            >
              ×
            </button>
          </div>
          {/* Divider */}
          <div className="h-[1px] bg-outline-variant mt-5 transition-colors" />
        </div>

        {/* ── Scrollable body ───────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">

          {/* Analysis */}
          <section className="rounded-xl border border-outline-variant p-5 bg-surface-container-lowest transition-colors">
            <SectionHeader>Analysis</SectionHeader>
            <div className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-[11px] font-medium text-on-surface-variant" htmlFor="timeRangeSelect">Default Time Range</label>
                <select id="timeRangeSelect" value={tempSettings.timeRange} onChange={(e) => set({ timeRange: e.target.value })} className={inputCls}>
                  <option value="7">Last 7 days</option>
                  <option value="30">Last 30 days</option>
                  <option value="90">Last 90 days</option>
                  <option value="365">Last 1 year</option>
                </select>
              </div>
              <Toggle id="autoAnalyzeToggle" checked={tempSettings.autoAnalyze} onChange={(v) => set({ autoAnalyze: v })} label="Auto-analyze on paste" description="Trigger analysis when a repository URL is detected" />
              <Toggle id="autoEmailToggle" checked={tempSettings.autoEmailReview} onChange={(v) => set({ autoEmailReview: v })} label="Email PR reviews" description="Send the report as soon as a review finishes" />
            </div>
          </section>

          {/* AI Provider & Keys */}
          <section className="rounded-xl border border-outline-variant p-5 bg-surface-container-lowest transition-colors">
            <SectionHeader>AI Provider &amp; Keys</SectionHeader>
            {serverCfg?.unavailable ? (
              <p className="text-[12px] text-on-surface-variant">Backend offline — start the API server to manage keys.</p>
            ) : !serverCfg ? (
              <p className="text-[12px] text-on-surface-variant">Loading…</p>
            ) : (
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-[11px] font-medium text-on-surface-variant" htmlFor="llmProviderSelect">AI Provider</label>
                  <select id="llmProviderSelect" value={keysForm.llm_provider} onChange={(e) => setKeys({ llm_provider: e.target.value })} className={inputCls}>
                    <option value="local">Local (LM Studio)</option>
                    <option value="claude">Claude (Anthropic)</option>
                    <option value="openai">OpenAI</option>
                    <option value="gemini">Gemini (Google)</option>
                  </select>
                </div>
                {keysForm.llm_provider === "local" ? (
                  <div className="space-y-1.5">
                    <label className="text-[11px] font-medium text-on-surface-variant" htmlFor="localLlmUrl">Local Server URL</label>
                    <input id="localLlmUrl" type="text" value={keysForm.local_llm_base_url} onChange={(e) => setKeys({ local_llm_base_url: e.target.value })} placeholder="http://localhost:1234/v1" className={`${inputCls} font-mono`} />
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <div className="flex justify-between">
                      <label className="text-[11px] font-medium text-on-surface-variant" htmlFor="llmApiKey">API Key</label>
                      {serverCfg[KEY_FIELD[keysForm.llm_provider]] === "***" && <span className="text-green-500 text-[10px] font-mono">configured ✓</span>}
                    </div>
                    <input id="llmApiKey" type="password" autoComplete="off" value={keysForm.api_key} onChange={(e) => setKeys({ api_key: e.target.value })} placeholder={serverCfg[KEY_FIELD[keysForm.llm_provider]] === "***" ? "•••• configured — paste to replace" : "paste your API key"} className={`${inputCls} font-mono`} />
                  </div>
                )}
                <div className="space-y-1.5">
                  <label className="text-[11px] font-medium text-on-surface-variant" htmlFor="llmModel">Model <span className="opacity-60">(optional)</span></label>
                  <input id="llmModel" type="text" value={keysForm.llm_model} onChange={(e) => setKeys({ llm_model: e.target.value })} placeholder="provider default" className={`${inputCls} font-mono`} />
                </div>
                <div className="space-y-1.5">
                  <div className="flex justify-between">
                    <label className="text-[11px] font-medium text-on-surface-variant" htmlFor="githubToken">GitHub Token</label>
                    {serverCfg.github_token === "***" && <span className="text-green-500 text-[10px] font-mono">configured ✓</span>}
                  </div>
                  <input id="githubToken" type="password" autoComplete="off" value={keysForm.github_token} onChange={(e) => setKeys({ github_token: e.target.value })} placeholder={serverCfg.github_token === "***" ? "•••• configured — paste to replace" : "ghp_… or github_pat_…"} className={`${inputCls} font-mono`} />
                  <p className="text-[10px] text-on-surface-variant leading-relaxed m-0">Raises GitHub rate limit from 60 to 5,000 req/h and powers developer profiles, PR reviews, and repo metadata.</p>
                </div>
                {keysMsg && (
                  <div className={`p-2.5 text-[12px] rounded-lg text-center border ${keysMsg.ok ? "bg-green-500/10 text-green-600 dark:text-green-400 border-green-500/20" : "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20"}`}>{keysMsg.text}</div>
                )}
                <button onClick={saveKeys} disabled={keysSaving} className="w-full border border-primary/40 text-primary bg-primary/10 py-2.5 text-[11px] font-bold rounded-lg hover:bg-primary/20 transition-colors uppercase tracking-[0.12em] disabled:opacity-50">
                  {keysSaving ? "Saving & testing…" : "Save & Test Keys"}
                </button>
              </div>
            )}
          </section>

          {/* About */}
          <section className="rounded-xl border border-outline-variant p-5 bg-surface-container-lowest transition-colors">
            <SectionHeader>About</SectionHeader>
            <div className="space-y-2">
              <div className="flex justify-between text-[13px] text-on-surface-variant">
                <span>Version</span>
                <span className="font-mono">{about?.version ? `v${about.version}` : about?.unavailable ? "offline" : "…"}</span>
              </div>
              <div className="flex justify-between text-[13px] text-on-surface-variant">
                <span>Store</span>
                <span className="font-mono uppercase">{about?.store || (about?.unavailable ? "unreachable" : "…")}</span>
              </div>
              <p className="text-[11px] text-on-surface-variant pt-2 m-0">RepoLens — GitHub analytics &amp; intelligence. Full diagnostics at /status.</p>
            </div>
          </section>

        </div>

        {/* ── Fixed footer — Save Changes ───────────────────────────────── */}
        <div className="p-4 px-6 pb-6 shrink-0 bg-surface-container border-t border-outline-variant transition-colors">
          {saveMsg && (
            <div className="mb-3 p-2 bg-green-500/10 text-green-600 dark:text-green-400 text-[12px] font-bold rounded-lg text-center border border-green-500/20">
              {saveMsg}
            </div>
          )}
          <button
            type="button"
            onClick={handleSave}
            className="w-full p-[14px] rounded-[10px] border-none bg-primary text-on-primary text-[12px] font-bold tracking-[0.12em] uppercase cursor-pointer transition-all duration-250 shadow-[0_0_22px_var(--tw-shadow-color),0_0_8px_var(--tw-shadow-color)] shadow-primary/45"
          >
            {saveMsg ? "Saved" : "Save Changes"}
          </button>
        </div>
      </aside>
    </>
  );
}
