import { useEffect, useState, useCallback, useRef, useContext } from "react";
import { useNavigate, Link } from "react-router-dom";
import { getJSON, postJSON } from "../lib/api";
import { loadRepoSettings, saveRepoSettings, getHeatmapColorStyle } from "../lib/settings";
import SyncBadge from "../components/SyncBadge";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar } from "recharts";
import { ThemeContext } from "../lib/theme";

// ─── Helpers ────────────────────────────────────────────────────────────────

function formatNumber(num) {
  if (num === undefined || num === null) return "0";
  return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function timeAgo(dateString) {
  if (!dateString) return "";
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now - date;
  if (isNaN(diffMs)) return "";
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// ─── Commit Quality Modal ────────────────────────────────────────────────────

function CommitQualityModal({ quality, activity, onClose, onRerun, triggeringQuality }) {
  const [activeTab, setActiveTab] = useState("overview");
  const [search, setSearch] = useState("");
  const modalRef = useRef(null);

  // Close on ESC
  useEffect(() => {
    const handler = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  // Close on outside click
  const handleBackdrop = (e) => {
    if (e.target === e.currentTarget) onClose();
  };

  const scoreColor = (score) => {
    if (score <= 4) return { badge: "bg-red-900/40 border-red-700/60 text-red-400", text: "text-red-400" };
    if (score <= 7) return { badge: "bg-orange-900/40 border-orange-700/60 text-orange-400", text: "text-orange-400" };
    return { badge: "bg-green-900/40 border-green-700/60 text-green-400", text: "text-green-400" };
  };

  const allCommits = quality?.worst || [];
  const filtered = allCommits.filter((c) => {
    const q = search.toLowerCase();
    return !q || c.subject?.toLowerCase().includes(q) || c.sha?.toLowerCase().includes(q);
  });

  return (
    <div
      className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4 backdrop-blur-sm"
      onClick={handleBackdrop}
    >
      <div
        ref={modalRef}
        className="bg-surface-container-high border border-outline-variant w-full max-w-2xl max-h-[85vh] flex flex-col rounded-xl shadow-2xl overflow-hidden"
        style={{ animation: "modalIn 0.18s ease-out" }}
      >
        {/* Sticky header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-outline-variant bg-surface-container-high shrink-0">
          <div className="space-y-0.5">
            <h2 className="font-code text-sm font-bold text-on-surface uppercase tracking-wider flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-primary">verified_user</span>
              Commit Quality Report
            </h2>
            <p className="text-[11px] text-on-surface-variant font-code">
              {quality?.commits} commits analysed · avg score{" "}
              <span className="text-primary font-bold">{quality?.avg_score?.toFixed(1)}/10</span>
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-on-surface-variant hover:text-primary transition-colors p-1 rounded-md hover:bg-surface-container"
            aria-label="Close modal"
          >
            <span className="material-symbols-outlined text-[22px]">close</span>
          </button>
        </div>

        {/* Tabs */}
        <div className="px-6 pt-2 border-b border-outline-variant bg-surface-container-high shrink-0 flex gap-6">
          {[
            { id: "overview", label: "Overview" },
            { id: "contributors", label: "Contributors" },
            { id: "worst", label: "Worst Commits" },
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`pb-2 text-[12px] font-code font-bold uppercase tracking-wider transition-colors border-b-2 ${
                activeTab === tab.id ? "border-primary text-primary" : "border-transparent text-on-surface-variant hover:text-on-surface"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === "overview" && (
          <div className="flex-1 overflow-y-auto p-6 flex flex-col items-center justify-center gap-8">
            <div className="flex flex-col md:flex-row items-center justify-center gap-12 w-full">
              {/* Big Dial */}
              <div className="flex flex-col items-center">
                <div
                  className="relative w-48 h-48 rounded-full flex items-center justify-center shadow-xl"
                  style={{
                    background: `radial-gradient(closest-side, var(--color-surface-container) 79%, transparent 80% 100%), conic-gradient(var(--color-primary) ${
                      ((quality?.avg_score || 0) / 10) * 100
                    }%, #222222 0)`
                  }}
                >
                  <div className="flex flex-col items-center">
                    <span className="font-stat text-5xl font-bold text-primary">{quality?.avg_score?.toFixed(1) || 0}</span>
                    <span className="font-code text-[10px] text-on-surface-variant uppercase tracking-widest mt-1">Avg Score</span>
                  </div>
                </div>
              </div>

              {/* Radar Chart */}
              <div className="w-[300px] h-[250px]">
                <ResponsiveContainer width="100%" height="100%">
                  <RadarChart
                    cx="50%" cy="50%" outerRadius="70%"
                    data={[
                      { subject: "Score", A: (quality?.avg_score || 0) * 10, fullMark: 100 },
                      { subject: "Imperative", A: quality?.pct_imperative || 0, fullMark: 100 },
                      { subject: "Referenced", A: quality?.pct_referenced || 0, fullMark: 100 },
                      { subject: "Clean", A: quality?.commits ? ((quality.commits - (quality.weak || 0)) / quality.commits) * 100 : 0, fullMark: 100 },
                    ]}
                  >
                    <PolarGrid stroke="rgba(255,255,255,0.1)" />
                    <PolarAngleAxis dataKey="subject" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10, fontFamily: 'monospace' }} />
                    <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
                    <Radar name="Quality" dataKey="A" stroke="var(--color-primary)" fill="var(--color-primary)" fillOpacity={0.3} />
                  </RadarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}

        {activeTab === "contributors" && (
          <div className="flex-1 overflow-y-auto p-6 scrollbar-thin">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {activity?.contributors?.map(c => (
                <div key={c.author} className="flex items-center gap-3 p-3 bg-surface-container border border-outline-variant/50 rounded-lg hover:border-outline-variant transition-colors">
                  <div className="w-10 h-10 shrink-0 rounded-full bg-primary/10 flex items-center justify-center font-code font-bold text-primary border border-primary/20">
                    {c.author.slice(0, 2).toUpperCase()}
                  </div>
                  <div className="flex flex-col min-w-0">
                    <span className="font-code font-bold text-[13px] text-on-surface truncate">{c.author}</span>
                    <span className="font-code text-[10px] text-on-surface-variant">{c.commits} commits</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === "worst" && (
          <div className="flex flex-col flex-1 min-h-0">
            {/* Search bar */}
            <div className="px-6 py-3 border-b border-outline-variant/50 bg-surface-container-high shrink-0">
              <div className="relative">
                <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[16px] text-on-surface-variant/60">
                  search
                </span>
                <input
                  type="text"
                  placeholder="Search commit message or hash…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full bg-surface-container border border-outline-variant rounded-lg pl-9 pr-3 py-2 text-[12px] font-code text-on-surface placeholder-on-surface-variant/40 focus:outline-none focus:border-primary transition-colors"
                />
              </div>
            </div>

            {/* Scrollable commit list */}
            <div className="overflow-y-auto flex-1 px-6 py-4 space-y-3 scrollbar-thin">
              {filtered.length === 0 && (
                <div className="text-center py-12 text-on-surface-variant font-code text-xs">
                  No commits match your search.
                </div>
              )}
              {filtered.map((wc, idx) => {
                const colors = scoreColor(wc.score);
                return (
                  <div
                    key={wc.sha}
                    className="bg-surface-container border border-outline-variant/50 rounded-lg p-4 space-y-3 hover:border-outline-variant transition-colors"
                  >
                    {/* Card header */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1 flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-[10px] font-code text-on-surface-variant/50">#{idx + 1}</span>
                          <code className="text-[11px] font-code text-primary/70 bg-black/30 px-2 py-0.5 rounded border border-outline-variant/30 select-all">
                            {wc.sha?.slice(0, 8)}
                          </code>
                        </div>
                        <p className="text-[13px] font-code text-on-surface font-medium leading-snug">
                          {wc.subject}
                        </p>
                        {wc.author && (
                          <p className="text-[10px] text-on-surface-variant/50 font-code">
                            by {wc.author}
                          </p>
                        )}
                      </div>
                      <span
                        className={`shrink-0 text-[13px] font-bold font-code px-3 py-1 rounded-full border ${colors.badge}`}
                      >
                        {wc.score}/10
                      </span>
                    </div>

                    {/* Issues */}
                    {wc.issues && wc.issues.length > 0 && (
                      <div className="space-y-1 pt-1 border-t border-outline-variant/30">
                        <p className="text-[9px] font-code text-on-surface-variant uppercase tracking-widest font-bold">Issues</p>
                        <ul className="space-y-1">
                          {wc.issues.map((issue, i) => (
                            <li
                              key={i}
                              className="flex items-start gap-2 text-[11px] text-on-surface-variant leading-snug"
                            >
                              <span className="text-error mt-0.5 shrink-0">•</span>
                              <span>{issue}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="px-6 py-3 border-t border-outline-variant/50 flex items-center justify-between bg-surface-container-high shrink-0">
          <span className="text-[10px] font-code text-on-surface-variant/50">
            CALCULATED: {timeAgo(quality?.generated_at)}
          </span>
          <button
            onClick={onRerun}
            disabled={triggeringQuality}
            className="font-code text-[10px] font-bold text-primary hover:text-primary-container transition-colors uppercase disabled:opacity-50"
          >
            {triggeringQuality ? "RE-RUNNING…" : "RE-RUN ANALYSIS"}
          </button>
        </div>
      </div>

      <style>{`
        @keyframes modalIn {
          from { opacity: 0; transform: translateY(12px) scale(0.98); }
          to   { opacity: 1; transform: translateY(0)    scale(1);    }
        }
      `}</style>
    </div>
  );
}

// ─── Settings Modal ──────────────────────────────────────────────────────────

function SettingsModal({ settingsForm, setSettingsForm, onSave, onClose }) {
  // Close on ESC
  useEffect(() => {
    const handler = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const handleBackdrop = (e) => {
    if (e.target === e.currentTarget) onClose();
  };

  return (
    <div
      className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4 backdrop-blur-sm"
      onClick={handleBackdrop}
    >
      <div
        className="bg-surface-container-high border border-outline-variant w-full max-w-[36rem] rounded-xl shadow-2xl overflow-hidden"
        style={{ animation: "modalIn 0.18s ease-out" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-8 py-5 border-b border-outline-variant">
          <div>
            <h2 className="font-code text-sm font-bold text-on-surface uppercase tracking-wider">
              Analysis Configuration
            </h2>
            <p className="text-[11px] text-on-surface-variant font-code mt-0.5">
              Adjust how the repository is analysed.
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-on-surface-variant hover:text-primary transition-colors p-1 rounded-md hover:bg-surface-container"
            aria-label="Close settings"
          >
            <span className="material-symbols-outlined text-[22px]">close</span>
          </button>
        </div>

        {/* Body */}
        <div className="px-8 py-6 flex flex-col gap-6 bg-surface">
          <div className="flex flex-col gap-2">
            <label className="font-code text-xs font-bold text-on-surface-variant uppercase tracking-wider">
              Max Commits To Analyze
            </label>
            <input
              type="number"
              value={settingsForm.max_commits || ""}
              onChange={(e) => setSettingsForm({ ...settingsForm, max_commits: e.target.value })}
              className="w-full max-w-[28rem] bg-surface-container border border-outline-variant rounded-lg px-4 py-2.5 text-sm font-code text-on-surface placeholder-on-surface-variant/40 focus:outline-none focus:border-primary transition-colors"
              placeholder="e.g. 250"
            />
            <p className="text-xs text-on-surface-variant/60 font-code leading-normal max-w-[28rem]">
              Higher values are more accurate but take longer to process.
            </p>
          </div>

          <div className="flex flex-col gap-2">
            <label className="font-code text-xs font-bold text-on-surface-variant uppercase tracking-wider">
              Top Scoring Hotspots Count
            </label>
            <input
              type="number"
              value={settingsForm.top || ""}
              onChange={(e) => setSettingsForm({ ...settingsForm, top: e.target.value })}
              className="w-full max-w-[28rem] bg-surface-container border border-outline-variant rounded-lg px-4 py-2.5 text-sm font-code text-on-surface placeholder-on-surface-variant/40 focus:outline-none focus:border-primary transition-colors"
              placeholder="e.g. 15"
            />
            <p className="text-xs text-on-surface-variant/60 font-code leading-normal max-w-[28rem]">
              Number of hotspot files ranked by churn + fix frequency.
            </p>
          </div>
        </div>

        {/* Divider + Actions */}
        <div className="px-8 py-5 border-t border-outline-variant flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            className="h-10 px-6 bg-surface-container hover:bg-surface-container-high border border-outline-variant text-on-surface font-code text-[12px] font-bold rounded-lg transition-all active:scale-95"
          >
            Cancel
          </button>
          <button
            onClick={onSave}
            className="h-10 px-6 bg-primary hover:bg-primary-container text-on-primary font-code text-[12px] font-bold rounded-lg transition-all shadow-sm shadow-primary/20 hover:shadow-primary/40 active:scale-95"
          >
            Save &amp; Analyze
          </button>
        </div>
      </div>

      <style>{`
        @keyframes modalIn {
          from { opacity: 0; transform: translateY(12px) scale(0.98); }
          to   { opacity: 1; transform: translateY(0)    scale(1);    }
        }
      `}</style>
    </div>
  );
}

// ─── Main Dashboard ──────────────────────────────────────────────────────────

export default function Dashboard() {
  const navigate = useNavigate();
  const repo = new URLSearchParams(window.location.search).get("repo");

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [triggeringInsights, setTriggeringInsights] = useState(false);
  const [triggeringQuality, setTriggeringQuality] = useState(false);
  const [triggeringAnalyze, setTriggeringAnalyze] = useState(false);

  // FIX #4: selectedYear derived from real data, never hardcoded
  const [selectedYear, setSelectedYear] = useState(null);

  const [showSettings, setShowSettings] = useState(false);
  const [showQualityModal, setShowQualityModal] = useState(false);

  const { settings } = useContext(ThemeContext);
  const getHeatmapStyle = (count) => {
    const c = getHeatmapColorStyle(count, settings.accentColor, settings.theme);
    // reference-design bloom: busy days glow
    return count > 5 ? { backgroundColor: c, boxShadow: `0 0 6px ${c}` } : { backgroundColor: c };
  };

  const [settingsForm, setSettingsForm] = useState(() => loadRepoSettings(repo));

  const insightsTimerRef = useRef(null);
  const qualityTimerRef = useRef(null);

  const getParsedSettings = useCallback(() => {
    const maxVal = parseInt(settingsForm.max_commits, 10);
    const topVal = parseInt(settingsForm.top, 10);
    return {
      max_commits: isNaN(maxVal) ? undefined : maxVal,
      top: isNaN(topVal) ? 50 : topVal,
    };
  }, [settingsForm]);

  const pollBackgroundInsights = useCallback((jobId) => {
    let timer;
    const tick = () => {
      getJSON(`/jobs/${jobId}`)
        .then((job) => {
          if (job.status === "done") {
            getJSON(`/repos/${repo}/insights`)
              .then((res) => setData((prev) => prev ? { ...prev, insights: res } : prev))
              .catch((e) => setData((prev) => prev ? { ...prev, insights: { unavailable: true, error: String(e) } } : prev));
          } else if (job.status === "failed") {
            setData((prev) => prev ? { ...prev, insights: { unavailable: true, error: job.error || "Generation failed." } } : prev);
          } else {
            timer = setTimeout(tick, 2000);
            insightsTimerRef.current = timer;
          }
        })
        .catch((e) => setData((prev) => prev ? { ...prev, insights: { unavailable: true, error: String(e) } } : prev));
    };
    timer = setTimeout(tick, 2000);
    insightsTimerRef.current = timer;
  }, [repo]);

  const pollBackgroundQuality = useCallback((jobId) => {
    let timer;
    const tick = () => {
      getJSON(`/jobs/${jobId}`)
        .then((job) => {
          if (job.status === "done") {
            getJSON(`/repos/${repo}/commit-quality`)
              .then((res) => setData((prev) => prev ? { ...prev, quality: res } : prev))
              .catch((e) => setData((prev) => prev ? { ...prev, quality: { unavailable: true, error: String(e) } } : prev));
          } else if (job.status === "failed") {
            setData((prev) => prev ? { ...prev, quality: { unavailable: true, error: job.error || "Generation failed." } } : prev);
          } else {
            timer = setTimeout(tick, 2000);
            qualityTimerRef.current = timer;
          }
        })
        .catch((e) => setData((prev) => prev ? { ...prev, quality: { unavailable: true, error: String(e) } } : prev));
    };
    timer = setTimeout(tick, 2000);
    qualityTimerRef.current = timer;
  }, [repo]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    const soft = (p) => getJSON(p).catch((e) => ({ error: String(e), unavailable: true }));

    try {
      let activityData;
      try {
        activityData = await getJSON(`/repos/${repo}/activity?days=${settings.timeRange || 365}&recent=15`);
      } catch (e) {
        if (e.message.includes("404") || e.message.includes("no cached commits") || e.message.includes("POST /analyze first")) {
          const parsed = getParsedSettings();
          const res = await postJSON("/analyze", { repo, refresh: false, max_commits: parsed.max_commits, top: parsed.top });
          navigate(`/loading?job=${res.job_id}&repo=${repo}&next=/dashboard`);
          return;
        } else {
          throw e;
        }
      }

      const [metaData, qualityData, insightsData, prData] = await Promise.all([
        soft(`/repos/${repo}/meta`),
        soft(`/repos/${repo}/commit-quality`),
        soft(`/repos/${repo}/insights`),
        soft(`/repos/${repo}/pr-reviews`),
      ]);

      let finalInsights = insightsData;
      if (insightsData.unavailable && insightsData.error && (insightsData.error.includes("404") || insightsData.error.includes("no insights"))) {
        try {
          const res = await postJSON(`/repos/${repo}/insights`);
          finalInsights = { generating: true, jobId: res.job_id, bullets: ["AI insights are being calculated in the background…"] };
          pollBackgroundInsights(res.job_id);
        } catch (err) {
          finalInsights = { unavailable: true, error: String(err) };
        }
      }

      let finalQuality = qualityData;
      if (qualityData.unavailable && qualityData.error && (qualityData.error.includes("404") || qualityData.error.includes("POST /commit-quality"))) {
        try {
          const parsed = getParsedSettings();
          const res = await postJSON("/commit-quality", { repo, max_commits: parsed.max_commits, top: parsed.top });
          finalQuality = { generating: true, jobId: res.job_id };
          pollBackgroundQuality(res.job_id);
        } catch (err) {
          finalQuality = { unavailable: true, error: String(err) };
        }
      }

      setData({ activity: activityData, meta: metaData, quality: finalQuality,
                insights: finalInsights,
                prReviews: (prData && prData.pr_reviews) || [] });
      setLoading(false);
    } catch (e) {
      setError(e.message);
      setLoading(false);
    }
  }, [repo, navigate, getParsedSettings, pollBackgroundInsights, pollBackgroundQuality,
      settings.timeRange]);

  useEffect(() => {
    if (repo) loadData();
    else setLoading(false);
    return () => {
      clearTimeout(insightsTimerRef.current);
      clearTimeout(qualityTimerRef.current);
    };
  }, [loadData, repo]);

  // FIX #4: derive selectedYear from actual heatmap data — no hardcoding
  useEffect(() => {
    if (data?.activity?.heatmap && data.activity.heatmap.length > 0) {
      const years = data.activity.heatmap
        .map((h) => parseInt(h.date?.split("-")[0], 10))
        .filter((yr) => !isNaN(yr));
      if (years.length > 0) {
        setSelectedYear(Math.max(...years));
      }
    }
  }, [data]);

  const handleReAnalyze = async () => {
    setTriggeringAnalyze(true);
    try {
      const parsed = getParsedSettings();
      const res = await postJSON("/analyze", { repo, refresh: true, max_commits: parsed.max_commits, top: parsed.top });
      navigate(`/loading?job=${res.job_id}&repo=${repo}&next=/dashboard`);
    } catch (e) {
      alert(`Analyze trigger failed: ${e.message}`);
      setTriggeringAnalyze(false);
    }
  };

  const handleTriggerQuality = async () => {
    setTriggeringQuality(true);
    try {
      const parsed = getParsedSettings();
      const res = await postJSON("/commit-quality", { repo, max_commits: parsed.max_commits, top: parsed.top });
      navigate(`/loading?job=${res.job_id}&repo=${repo}&next=/dashboard`);
    } catch (e) {
      alert(`Commit quality trigger failed: ${e.message}`);
      setTriggeringQuality(false);
    }
  };

  const handleTriggerInsights = async () => {
    setTriggeringInsights(true);
    try {
      const res = await postJSON(`/repos/${repo}/insights`);
      setData((prev) => prev ? {
        ...prev,
        insights: { generating: true, jobId: res.job_id, bullets: ["AI insights are being calculated in the background…"] }
      } : prev);
      pollBackgroundInsights(res.job_id);
      setTriggeringInsights(false);
    } catch (e) {
      alert(`AI Insights trigger failed: ${e.message}`);
      setTriggeringInsights(false);
    }
  };

  const handleSaveSettings = () => {
    saveRepoSettings(repo, settingsForm);
    setShowSettings(false);
    handleReAnalyze();
  };

  // ── Empty / loading / error states ────────────────────────────────────────

  if (!repo) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface p-6 relative overflow-hidden">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-primary/5 rounded-full blur-[100px] pointer-events-none" />
        <div className="relative w-full max-w-[460px] p-10 rounded-3xl bg-surface-container-lowest/60 backdrop-blur-xl border border-outline-variant/40 shadow-2xl shadow-primary/10 text-center flex flex-col items-center gap-6">
          <div className="w-20 h-20 rounded-full bg-primary/10 flex items-center justify-center border border-primary/20 shadow-inner">
            <span className="material-symbols-outlined text-primary text-[40px]">link_off</span>
          </div>
          <div className="space-y-3">
            <h2 className="font-display-lg text-3xl text-on-surface font-bold tracking-tight">Missing Link</h2>
            <p className="text-sm text-on-surface-variant leading-relaxed px-2 font-body">
              We need a valid GitHub repository link. Please return to the home page to enter one.
            </p>
          </div>
          <Link
            to="/"
            className="w-full bg-primary hover:bg-primary-container text-on-primary font-code font-bold py-3.5 rounded-xl transition-all duration-300 active:scale-95 text-center flex items-center justify-center gap-2 mt-2 shadow-lg shadow-primary/20"
          >
            <span className="material-symbols-outlined text-[20px]">arrow_back</span>
            Return Home
          </Link>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-primary border-t-transparent rounded-full motion-safe:animate-spin mx-auto" />
          <p className="font-code text-label text-on-surface-variant uppercase tracking-widest animate-pulse">
            Loading dashboard…
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface p-6">
        <div className="max-w-[28rem] w-full bg-surface border border-outline-variant p-6 space-y-4 text-center shadow-lg rounded-xl">
          <span className="material-symbols-outlined text-error text-[48px]">warning</span>
          <h2 className="font-code text-heading-lg text-primary">Failed to load dashboard</h2>
          <p className="text-xs text-on-surface-variant leading-relaxed break-words">{error}</p>
          <button
            onClick={() => navigate("/")}
            className="w-full bg-primary hover:bg-primary-container text-on-primary font-code font-bold py-2 px-4 transition-all rounded-lg"
          >
            Return home
          </button>
        </div>
      </div>
    );
  }

  // ── Data + derived state ───────────────────────────────────────────────────

  const { activity, meta, quality, insights, prReviews = [] } = data;
  const prLevel = (lvl) =>
    lvl === "HIGH" ? "bg-red-500/20 text-red-400 border-red-500/30"
    : lvl === "MEDIUM" ? "bg-orange-400/20 text-orange-400 border-orange-400/30"
    : "bg-green-500/20 text-green-500 border-green-500/30";
  const hasMeta = meta && !meta.unavailable;
  const hasQuality = data.quality && !data.quality.unavailable && !data.quality.generating;
  const hasInsights = insights && !insights.unavailable;

  // FIX #4: available years come entirely from heatmap data
  const availableYears = (() => {
    const heatmapData = activity?.heatmap || [];
    const yearsSet = new Set();
    heatmapData.forEach((h) => {
      if (h.date) {
        const yr = parseInt(h.date.split("-")[0], 10);
        if (!isNaN(yr)) yearsSet.add(yr);
      }
    });
    return Array.from(yearsSet).sort((a, b) => b - a);
  })();

  // If selectedYear not yet set (null), derive from data or fall back to first available
  const activeYear = selectedYear ?? availableYears[0] ?? new Date().getFullYear();

  const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

  const generateHeatmapGrid = () => {
    const cells = [];
    const heatmapLookup = {};
    (activity?.heatmap || []).forEach((h) => { if (h.date) heatmapLookup[h.date] = h.count; });

    const jan1 = new Date(Date.UTC(activeYear, 0, 1));
    const startPadding = jan1.getUTCDay();
    for (let i = 0; i < startPadding; i++) cells.push({ isPadding: true });

    let current = new Date(Date.UTC(activeYear, 0, 1));
    while (current.getUTCFullYear() === activeYear) {
      const dateStr = current.toISOString().split("T")[0];
      const count = heatmapLookup[dateStr] || 0;
      const dayOfWeek = current.getUTCDay();
      cells.push({
        date: dateStr, count, dayOfWeek, isPadding: false,
        title: `${dateStr} (${WEEKDAYS[dayOfWeek]}): ${count} commit${count === 1 ? "" : "s"}`,
      });
      current.setUTCDate(current.getUTCDate() + 1);
    }

    const lastCell = cells[cells.length - 1];
    const lastDayOfWeek = lastCell ? (lastCell.dayOfWeek ?? 6) : 6;
    const endPadding = 6 - lastDayOfWeek;
    for (let i = 0; i < endPadding; i++) cells.push({ isPadding: true });

    return cells;
  };

  const heatmapCells = generateHeatmapGrid();
  const totalColumns = Math.ceil(heatmapCells.length / 7);

  const getMonthLabels = (cellsList) => {
    const labels = [];
    let lastMonth = -1;
    let lastColIndex = -3;
    cellsList.forEach((cell, idx) => {
      if (!cell.isPadding) {
        const month = parseInt(cell.date.split("-")[1], 10) - 1;
        if (month !== lastMonth) {
          const colIndex = Math.floor(idx / 7);
          if (colIndex - lastColIndex >= 2) {
            labels.push({ text: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][month], colIndex });
            lastColIndex = colIndex;
          }
          lastMonth = month;
        }
      }
    });
    return labels;
  };

  const monthLabels = getMonthLabels(heatmapCells);


  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-background text-on-surface font-body">

      {/* Modals */}
      {showSettings && (
        <SettingsModal
          settingsForm={settingsForm}
          setSettingsForm={setSettingsForm}
          onSave={handleSaveSettings}
          onClose={() => setShowSettings(false)}
        />
      )}
      {showQualityModal && hasQuality && (
        <CommitQualityModal
          quality={quality}
          activity={activity}
          onClose={() => setShowQualityModal(false)}
          onRerun={handleTriggerQuality}
          triggeringQuality={triggeringQuality}
        />
      )}

      <main className="pt-8 px-gutter max-w-container-max mx-auto pb-24">

        {/* ── Repo Header ──────────────────────────────────────────────────── */}
        <section className="mb-16">
          <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-6 lg:gap-10">
            <div className="flex-1 space-y-4">
              <div className="flex flex-wrap items-center gap-3 font-code">
                <h1 className="text-heading-lg text-3xl font-bold leading-none tracking-tight">
                  {hasMeta ? meta.full_name : repo}
                </h1>
                <SyncBadge timestamp={hasMeta ? meta.generated_at : undefined} onRefresh={handleReAnalyze} />
                {hasMeta && (
                  <div className="flex items-center gap-1.5 px-2.5 py-1 bg-surface-container-high border border-outline-variant/50 rounded-full">
                    <span
                      className="w-2.5 h-2.5 rounded-full"
                      style={{
                        backgroundColor:
                          meta.language === "JavaScript" || meta.language === "TypeScript" ? "#f1e05a"
                            : meta.language === "Python" ? "#3572a5"
                              : meta.language === "Rust" ? "#dea584"
                                : "#8b8b8b",
                      }}
                    />
                    <span className="text-[11px] font-bold text-on-surface-variant leading-none">{meta.language}</span>
                  </div>
                )}
              </div>
              <p className="text-on-surface-variant max-w-2xl text-[14px] leading-relaxed">
                {hasMeta ? meta.description : "Local workspace directory parsed and indexed."}
              </p>
              {hasMeta && (
                <div className="flex flex-wrap items-center gap-4 pt-1">
                  <span className="px-2.5 py-1 bg-surface-container border border-outline-variant/50 text-[11px] uppercase font-bold tracking-wider text-on-surface-variant rounded-md">
                    {meta.visibility}
                  </span>
                  <span className="flex items-center gap-1.5 text-[13px] text-on-surface-variant font-medium">
                    <span className="material-symbols-outlined text-[16px] text-primary">star</span>
                    {formatNumber(meta.stars)} stars
                  </span>
                  <span className="flex items-center gap-1.5 text-[13px] text-on-surface-variant font-medium">
                    <span className="material-symbols-outlined text-[16px] text-primary">fork_right</span>
                    {formatNumber(meta.forks)} forks
                  </span>
                </div>
              )}
            </div>

            <div className="flex flex-wrap sm:grid sm:grid-cols-2 lg:flex lg:justify-end gap-3 shrink-0">
              <button
                onClick={() => setShowSettings(true)}
                disabled={triggeringAnalyze}
                className="h-10 px-4 bg-surface-container hover:bg-surface-container-high border border-outline-variant text-on-surface font-code text-[12px] font-bold flex items-center justify-center gap-2 rounded-lg transition-all active:scale-95 disabled:opacity-50"
              >
                <span className="material-symbols-outlined text-[18px]">settings</span>
                CONFIG
              </button>
              <button
                onClick={handleReAnalyze}
                disabled={triggeringAnalyze}
                className="h-10 px-4 bg-surface-container hover:bg-surface-container-high border border-outline-variant text-on-surface font-code text-[12px] font-bold flex items-center justify-center gap-2 rounded-lg transition-all active:scale-95 disabled:opacity-50"
              >
                <span className="material-symbols-outlined text-[18px]">refresh</span>
                RE-ANALYZE
              </button>
              <button
                onClick={() => navigate(`/hotspots?repo=${repo}`)}
                className="h-10 px-4 bg-primary hover:bg-primary-container text-on-primary font-code text-[12px] font-bold flex items-center justify-center gap-2 rounded-lg transition-all shadow-sm shadow-primary/20 hover:shadow-primary/40 active:scale-95"
              >
                <span className="material-symbols-outlined text-[18px]">visibility</span>
                BUG HOTSPOTS
              </button>
              {hasMeta && meta.url && (
                <a
                  href={meta.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="h-10 px-4 bg-surface-container hover:bg-surface-container-high border border-outline-variant text-on-surface font-code text-[12px] font-bold flex items-center justify-center gap-2 rounded-lg transition-all active:scale-95"
                >
                  <span className="material-symbols-outlined text-[18px]">open_in_new</span>
                  GITHUB
                </a>
              )}
            </div>
          </div>
        </section>

        {/* ── Stats Row ────────────────────────────────────────────────────── */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-16">
          <div className="bg-surface-container border border-outline-variant p-5 space-y-2 rounded-xl">
            <p className="text-[10px] text-on-surface-variant font-code uppercase tracking-widest">Contributors</p>
            <div className="flex items-baseline gap-2">
              <span className="font-stat text-3xl font-bold">{activity.contributors_total}</span>
              <span className="text-label text-primary text-xs">active authors</span>
            </div>
            <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
              <div className="bg-primary h-full w-[60%]" />
            </div>
          </div>

          <div className="bg-surface-container border border-outline-variant p-5 space-y-2 rounded-xl">
            <p className="text-[10px] text-on-surface-variant font-code uppercase tracking-widest">Total Commits</p>
            <div className="flex items-baseline gap-2">
              <span className="font-stat text-3xl font-bold">{formatNumber(activity.total_commits)}</span>
              <span className="text-label text-on-surface-variant text-xs">historical</span>
            </div>
            <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
              <div className="bg-primary h-full w-[85%]" />
            </div>
          </div>

          <div className="bg-surface-container border border-outline-variant p-5 space-y-2 rounded-xl">
            <p className="text-[10px] text-on-surface-variant font-code uppercase tracking-widest">Open Issues</p>
            <div className="flex items-baseline gap-2">
              <span className="font-stat text-3xl font-bold">
                {hasMeta ? formatNumber(meta.open_issues) : "N/A"}
              </span>
              <span className={`text-label text-xs ${hasMeta && meta.open_issues > 0 ? "text-error" : "text-on-surface-variant"}`}>
                {hasMeta && meta.open_issues > 0 ? "▲ active" : "stable"}
              </span>
            </div>
            <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
              <div className={`h-full ${hasMeta && meta.open_issues > 0 ? "bg-error" : "bg-primary"} w-[25%]`} />
            </div>
          </div>

          <div className="relative bg-surface-container border border-outline-variant p-5 space-y-2 rounded-xl group cursor-help">
            <p className="text-[10px] text-on-surface-variant font-code uppercase tracking-widest flex justify-between">
              <span>Health Score</span>
              <span className="material-symbols-outlined text-xs">info</span>
            </p>
            <div className="flex items-baseline gap-2">
              <span className="font-stat text-3xl font-bold text-primary">
                {activity.health.score !== null ? activity.health.score.toFixed(1) : "N/A"}
              </span>
              <span className="text-label text-primary text-xs">▲ stable</span>
            </div>
            <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
              <div className="bg-primary h-full" style={{ width: `${(activity.health.score || 0) * 10}%` }} />
            </div>
            <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-64 bg-surface-container-highest border border-outline-variant p-3 text-xs opacity-0 group-hover:opacity-100 transition-opacity z-30 pointer-events-none rounded-xl shadow-xl font-code space-y-1.5">
              <p className="text-primary font-bold">Transparency Index Formula:</p>
              <p className="text-on-surface-variant text-[10px] leading-relaxed">{activity.health.formula || "Stability formula unresolved."}</p>
              <div className="grid grid-cols-2 gap-2 text-[10px] pt-1.5 border-t border-outline-variant/30 text-on-surface-variant">
                <div>stability: {activity.health.stability?.toFixed(1) || "10.0"}</div>
                <div>quality: {activity.health.commit_quality?.toFixed(1) || "N/A"}</div>
              </div>
            </div>
          </div>
        </section>

        {/* ── Heatmap ──────────────────────────────────────────────────────── */}
        <section className="bg-surface-container border border-outline-variant p-6 overflow-x-auto scrollbar-thin rounded-xl mb-16">
          <div className="flex justify-between items-center mb-6 min-w-[800px]">
            <div className="flex items-center gap-4">
              <p className="text-[11px] text-on-surface-variant font-code font-bold uppercase tracking-widest">
                Annual Contribution Velocity
              </p>
              {/* FIX #4: year selector only shows years present in actual data */}
              {availableYears.length > 1 && (
                <select
                  value={activeYear}
                  onChange={(e) => setSelectedYear(parseInt(e.target.value, 10))}
                  className="bg-surface-container border border-outline-variant text-on-surface text-[10px] font-code rounded px-2 py-0.5 outline-none cursor-pointer hover:border-outline focus:ring-1 focus:ring-primary"
                >
                  {availableYears.map((yr) => (
                    <option key={yr} value={yr}>{yr}</option>
                  ))}
                </select>
              )}
              {availableYears.length === 1 && (
                <span className="text-[11px] font-code text-on-surface-variant border border-outline-variant/40 px-2 py-0.5 rounded">
                  {availableYears[0]}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 font-code text-[11px] text-on-surface-variant">
              <span>Less</span>
              <div className="flex gap-1">
                {[0, 2, 5, 8, 12].map((val) => (
                  <div
                    key={val}
                    className={`w-[13px] h-[13px] rounded-sm ${val === 0 ? "border border-outline-variant/30" : ""}`}
                    style={getHeatmapStyle(val)}
                  />
                ))}
              </div>
              <span>More</span>
            </div>
          </div>

          <div className="min-w-[800px] flex flex-col">
            <div className="flex gap-3 mb-1.5">
              <div className="w-[24px] shrink-0" />
              <div className="flex-grow grid grid-flow-col gap-1 text-[9px] text-on-surface-variant/70 font-code select-none">
                {Array.from({ length: totalColumns }).map((_, colIdx) => {
                  const label = monthLabels.find((l) => l.colIndex === colIdx);
                  return (
                    <span key={colIdx} className="w-[13px] overflow-visible whitespace-nowrap text-left leading-none">
                      {label ? label.text : ""}
                    </span>
                  );
                })}
              </div>
            </div>
            <div className="flex gap-3">
              <div className="w-[24px] grid grid-rows-7 gap-1 text-[9px] text-on-surface-variant/70 font-code select-none h-[115px] items-center text-right pr-1 shrink-0">
                {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
                  <span key={d} className="leading-none">{d}</span>
                ))}
              </div>
              <div className="flex-grow grid grid-flow-col grid-rows-7 gap-1 h-[115px]">
                {heatmapCells.map((cell, idx) =>
                  cell.isPadding ? (
                    <div key={idx} className="w-[13px] h-[13px] opacity-0 pointer-events-none" />
                  ) : (
                    <div
                      key={idx}
                      title={cell.title}
                      className={`w-[13px] h-[13px] rounded-[3px] transition-all duration-200 hover:ring-2 hover:ring-primary/60 cursor-crosshair ${cell.count === 0 ? "border border-outline-variant/30" : ""}`}
                      style={getHeatmapStyle(cell.count)}
                    />
                  )
                )}
              </div>
            </div>
          </div>
        </section>

        {/* ── Two Column ───────────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">

          {/* Left Column */}
          <div className="lg:col-span-7 space-y-8">

            {/* Top Contributors */}
            <div className="bg-surface-container border border-outline-variant rounded-xl overflow-hidden">
              <div className="p-4 border-b border-outline-variant flex justify-between items-center">
                <p className="text-[10px] text-on-surface-variant font-code font-bold uppercase tracking-widest">Top Contributors</p>
                <span className="text-[10px] font-code text-on-surface-variant uppercase">{activity.contributors.length} indexed</span>
              </div>
              <div className="divide-y divide-outline-variant max-h-[360px] overflow-y-auto pr-1 scrollbar-thin">
                {activity.contributors.map((c) => (
                  <div key={c.author} className="p-3.5 flex items-center gap-4 hover:bg-surface-container-high transition-colors group">
                    <div className="w-8 h-8 rounded-lg bg-surface-container-highest flex items-center justify-center font-code font-bold text-xs border border-outline-variant/30 select-none">
                      {c.author.slice(0, 2).toUpperCase()}
                    </div>
                    <div className="flex-grow space-y-1">
                      <div className="flex justify-between items-baseline">
                        <span className="font-code text-code text-on-surface group-hover:text-primary transition-colors">{c.author}</span>
                        <span className="text-[10px] text-on-surface-variant font-code">{c.commits} commits ({Math.round(c.share * 100)}%)</span>
                      </div>
                      <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
                        <div className="bg-primary h-full transition-all duration-500" style={{ width: `${c.share * 100}%` }} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Recent Commits */}
            <div className="bg-surface-container border border-outline-variant rounded-xl overflow-hidden">
              <div className="p-4 border-b border-outline-variant flex justify-between items-center">
                <p className="text-[10px] text-on-surface-variant font-code font-bold uppercase tracking-widest">Recent Commits</p>
                <span className="text-[10px] font-code text-on-surface-variant uppercase">recent {activity.recent_commits.length}</span>
              </div>
              <div className="divide-y divide-outline-variant">
                {activity.recent_commits.map((c) => (
                  <div key={c.sha} className="p-3 flex items-start justify-between gap-4 hover:bg-surface-container-high transition-colors">
                    <div className="space-y-1 flex-grow">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-code text-code text-on-surface font-medium leading-tight">{c.subject}</span>
                        {c.is_bugfix && (
                          <span className="px-1.5 py-0.5 rounded bg-error-container/20 border border-error-container/50 text-error text-[8px] font-code uppercase select-none">
                            BUGFIX
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 text-[10px] text-on-surface-variant/60 font-code">
                        <span>by <span className="text-on-surface">{c.author}</span></span>
                        <span>•</span>
                        <span>{timeAgo(c.date) || c.date.slice(0, 10)}</span>
                      </div>
                    </div>
                    <span className="font-code text-[11px] text-primary/70 bg-surface-container-highest px-2 py-0.5 border border-outline-variant/30 select-all rounded shrink-0">
                      {c.sha.slice(0, 7)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right Column */}
          <div className="lg:col-span-5 space-y-8">

            {/* AI Insights */}
            <div className="bg-surface-container border border-outline-variant rounded-xl p-5 space-y-4">
              <div className="flex items-center justify-between border-b border-outline-variant pb-3">
                <p className="text-[10px] text-on-surface-variant font-code font-bold uppercase tracking-widest flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-sm text-primary">auto_awesome</span>
                  AI Repo Insights
                </p>
                {hasInsights && (
                  <span className="text-[9px] font-code text-on-surface-variant opacity-60">
                    {insights.provider?.split(" (")[0] || "LLM"}
                  </span>
                )}
              </div>

              {!hasInsights ? (
                <div className="text-center py-6 space-y-3 font-code">
                  <p className="text-xs text-on-surface-variant">AI insights report not generated yet.</p>
                  <button
                    onClick={handleTriggerInsights}
                    disabled={triggeringInsights}
                    className="bg-primary hover:bg-primary-container text-on-primary text-[10px] font-bold px-4 py-2 rounded-lg cursor-pointer disabled:opacity-50 transition-all"
                  >
                    {triggeringInsights ? "Generating…" : "Generate AI Insights"}
                  </button>
                  {insights?.error && (
                    <p className="text-[10px] text-error bg-error-container/10 border border-error-container/20 p-2 rounded-lg leading-relaxed">
                      {insights.error}
                    </p>
                  )}
                </div>
              ) : (
                <div className="space-y-3">
                  <ul className="list-none space-y-2">
                    {insights.bullets.map((bullet, idx) => (
                      <li key={idx} className="text-xs text-on-surface/90 flex items-start gap-2 leading-relaxed">
                        <span className="text-primary font-bold mt-0.5">◈</span>
                        <span>{bullet}</span>
                      </li>
                    ))}
                  </ul>
                  {insights.generating && (
                    <div className="flex items-center gap-2 text-[10px] text-primary/80 font-code animate-pulse pt-2">
                      <span className="w-1.5 h-1.5 bg-primary rounded-full animate-ping" />
                      Calculating AI profiles…
                    </div>
                  )}
                  {insights.generated_at && (
                    <div className="pt-2 flex justify-between items-center text-[9px] text-on-surface-variant/50 font-code border-t border-outline-variant/30 mt-2">
                      <span>Generated {timeAgo(insights.generated_at)}</span>
                      <button
                        onClick={handleTriggerInsights}
                        disabled={triggeringInsights}
                        className="hover:text-primary transition-colors uppercase cursor-pointer"
                      >
                        {triggeringInsights ? "Rebuilding…" : "Rebuild"}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Commit Quality Card — FIX #5/#6/#7: now opens modal */}
            <div className="bg-surface-container border border-outline-variant rounded-xl p-5 space-y-4">
              <div className="flex items-center justify-between border-b border-outline-variant pb-3">
                <p className="text-[10px] text-on-surface-variant font-code font-bold uppercase tracking-widest flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-sm text-primary">verified_user</span>
                  Commit Quality
                </p>
                {hasQuality && (
                  <span className="text-[9px] font-code text-on-surface-variant opacity-60">
                    avg {quality.avg_score?.toFixed(2)}/10
                  </span>
                )}
              </div>

              {!hasQuality ? (
                <div className="text-center py-6 space-y-3 font-code">
                  {data.quality?.generating ? (
                    <>
                      <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full motion-safe:animate-spin mx-auto" />
                      <p className="text-xs text-on-surface-variant animate-pulse">Running quality analysis…</p>
                    </>
                  ) : (
                    <>
                      <p className="text-xs text-on-surface-variant">Quality diagnostics not calculated yet.</p>
                      <button
                        onClick={handleTriggerQuality}
                        disabled={triggeringQuality}
                        className="bg-primary hover:bg-primary-container text-on-primary text-[10px] font-bold px-4 py-2 rounded-lg cursor-pointer disabled:opacity-50 transition-all"
                      >
                        {triggeringQuality ? "Generating…" : "Run Quality Analysis"}
                      </button>
                    </>
                  )}
                </div>
              ) : (
                <div className="space-y-5">
                  {/* Metrics grid */}
                  <div className="grid grid-cols-2 gap-3 text-xs font-code">
                    {[
                      { label: "Avg Score", value: `${quality.avg_score?.toFixed(1)}/10`, color: "text-primary" },
                      { label: "Weak Commits", value: `${quality.weak} / ${quality.commits}`, color: "text-error" },
                      { label: "Imperative Verbs", value: `${quality.pct_imperative}%`, color: "" },
                      { label: "Issue References", value: `${quality.pct_referenced}%`, color: "" },
                    ].map(({ label, value, color }) => (
                      <div key={label} className="p-3 bg-surface-container-high border border-outline-variant/30 rounded-lg">
                        <span className="text-[10px] text-on-surface-variant block uppercase font-bold mb-1">{label}</span>
                        <span className={`text-lg font-bold block ${color}`}>{value}</span>
                      </div>
                    ))}
                  </div>

                  {/* Trend chart */}
                  {quality.trend?.length > 0 && (
                    <div className="space-y-1.5">
                      <span className="font-code text-[9px] text-on-surface-variant uppercase tracking-wider block font-bold">Quality Trend</span>
                      <div className="h-24 w-full">
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={quality.trend}>
                            <XAxis dataKey="month" hide />
                            <YAxis domain={[0, 10]} hide />
                            <Tooltip
                              contentStyle={{ background: "#201f1f", border: "1px solid #554336", fontSize: "10px", fontFamily: "monospace" }}
                              itemStyle={{ color: "#ffb77d" }}
                              labelStyle={{ color: "#e5e2e1" }}
                            />
                            <Line type="monotone" dataKey="avg_score" stroke="#ffb77d" strokeWidth={2} dot={false} />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  )}

                  {/* Common issues */}
                  {quality.common_issues?.length > 0 && (
                    <div className="space-y-1.5 font-code">
                      <span className="text-[9px] text-on-surface-variant uppercase tracking-wider block font-bold">Common Diagnostics</span>
                      <div className="flex flex-wrap gap-1.5">
                        {quality.common_issues.slice(0, 5).map(([issue, count]) => (
                          <span key={issue} className="px-2 py-0.5 bg-surface-container-lowest text-[10px] border border-outline-variant/40 text-on-surface-variant hover:border-primary transition-colors cursor-default rounded">
                            {issue}: {count}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Open full modal button */}
                  <button
                    onClick={() => setShowQualityModal(true)}
                    className="w-full h-9 bg-surface-container-high hover:bg-surface-container border border-outline-variant text-on-surface font-code text-[11px] font-bold flex items-center justify-center gap-2 rounded-lg transition-all active:scale-95"
                  >
                    <span className="material-symbols-outlined text-[16px] text-primary">open_in_full</span>
                    View Full Quality Report
                  </button>

                  {/* Footer */}
                  <div className="flex justify-between items-center text-[9px] text-on-surface-variant/50 font-code border-t border-outline-variant/30 pt-2">
                    <span>Calculated {timeAgo(quality.generated_at)}</span>
                    <button
                      onClick={handleTriggerQuality}
                      disabled={triggeringQuality}
                      className="hover:text-primary transition-colors uppercase cursor-pointer"
                    >
                      {triggeringQuality ? "Re-running…" : "Re-run"}
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Language Inventory */}
            {hasMeta && meta.languages?.length > 0 && (
              <div className="bg-surface-container border border-outline-variant rounded-xl p-5 space-y-3">
                <p className="text-[10px] text-on-surface-variant font-code font-bold uppercase tracking-widest border-b border-outline-variant pb-3">Language Inventory</p>
                <div className="space-y-3 pt-1">
                  {meta.languages.slice(0, 4).map((lang) => (
                    <div key={lang.name} className="space-y-1">
                      <div className="flex justify-between text-xs font-code">
                        <span className="text-on-surface">{lang.name}</span>
                        <span className="text-on-surface-variant">{lang.pct.toFixed(1)}%</span>
                      </div>
                      <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
                        <div className="h-full bg-primary" style={{ width: `${lang.pct}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Pull Requests — reviewed PRs for this repo (Tool 3) */}
            <div className="bg-surface-container border border-outline-variant rounded-xl p-5 space-y-3 glow-card">
              <div className="flex items-center justify-between border-b border-outline-variant pb-3">
                <p className="text-[10px] text-on-surface-variant font-code font-bold uppercase tracking-widest">Pull Requests</p>
                <span className="material-symbols-outlined text-[16px] text-on-surface-variant">merge</span>
              </div>
              {prReviews.length > 0 ? (
                <div className="space-y-2 pt-1">
                  {prReviews.slice(0, 4).map((pr) => (
                    <Link
                      key={pr.number}
                      to={`/pr-review?repo=${repo}&pr=${pr.number}`}
                      className="flex items-center justify-between p-2.5 rounded-lg bg-surface-container-high hover:bg-surface-container-highest border border-outline-variant/30 hover:border-primary/50 transition-all group"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="material-symbols-outlined text-[15px] text-primary shrink-0">commit</span>
                        <span className="font-code text-xs text-on-surface group-hover:text-primary transition-colors">#{pr.number}</span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-sm uppercase border ${prLevel(pr.level)}`}>
                          {pr.level}
                        </span>
                        <span className="material-symbols-outlined text-[14px] text-on-surface-variant group-hover:text-primary group-hover:translate-x-0.5 transition-all">arrow_forward</span>
                      </div>
                    </Link>
                  ))}
                  {prReviews.length > 4 && (
                    <Link to={`/pr-review?repo=${repo}`} className="block text-center text-[11px] font-code text-primary hover:underline pt-1">
                      View all {prReviews.length} reviewed PRs →
                    </Link>
                  )}
                </div>
              ) : (
                <div className="pt-1 space-y-3">
                  <p className="text-xs text-on-surface-variant font-body">No PRs reviewed yet for this repository.</p>
                  <Link
                    to={`/pr-review?repo=${repo}`}
                    className="inline-flex items-center gap-1.5 text-[11px] font-code font-bold text-primary hover:underline"
                  >
                    <span className="material-symbols-outlined text-[14px]">rate_review</span>
                    Review a pull request →
                  </Link>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
