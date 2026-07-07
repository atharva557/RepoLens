import { useEffect, useState, useCallback, useRef } from "react";
import { useNavigate, Link } from "react-router-dom";
import { getJSON, postJSON } from "../lib/api";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";


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

export default function Dashboard() {
  const navigate = useNavigate();
  const repo = new URLSearchParams(window.location.search).get("repo");

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [triggeringInsights, setTriggeringInsights] = useState(false);
  const [triggeringQuality, setTriggeringQuality] = useState(false);
  const [triggeringAnalyze, setTriggeringAnalyze] = useState(false);

  // Settings dropdown modal state
  const [showSettings, setShowSettings] = useState(false);
  const [settingsForm, setSettingsForm] = useState(() => {
    try {
      const saved = localStorage.getItem("repolens_config");
      return saved ? JSON.parse(saved) : { maxCommits: "250", topCount: "15" };
    } catch {
      return { maxCommits: "250", topCount: "15" };
    }
  });

  const insightsTimerRef = useRef(null);

  const getParsedSettings = useCallback(() => {
    const maxVal = parseInt(settingsForm.maxCommits, 10);
    const topVal = parseInt(settingsForm.topCount, 10);
    return {
      max_commits: isNaN(maxVal) ? undefined : maxVal,
      top: isNaN(topVal) ? 15 : topVal,
    };
  }, [settingsForm]);

  const pollBackgroundInsights = useCallback((jobId) => {
    let timer;
    const tick = () => {
      getJSON(`/jobs/${jobId}`)
        .then((job) => {
          if (job.status === "done") {
            getJSON(`/repos/${repo}/insights`)
              .then((res) => {
                setData((prev) => {
                  if (!prev) return prev;
                  return { ...prev, insights: res };
                });
              })
              .catch((e) => {
                setData((prev) => {
                  if (!prev) return prev;
                  return { ...prev, insights: { unavailable: true, error: String(e) } };
                });
              });
          } else if (job.status === "failed") {
            setData((prev) => {
              if (!prev) return prev;
              return { ...prev, insights: { unavailable: true, error: job.error || "Generation failed." } };
            });
          } else {
            timer = setTimeout(tick, 2000);
            insightsTimerRef.current = timer;
          }
        })
        .catch((e) => {
          setData((prev) => {
            if (!prev) return prev;
            return { ...prev, insights: { unavailable: true, error: String(e) } };
          });
        });
    };
    timer = setTimeout(tick, 2000);
    insightsTimerRef.current = timer;
  }, [repo]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    const soft = (p) => getJSON(p).catch((e) => ({ error: String(e), unavailable: true }));

    try {
      let activityData;
      try {
        activityData = await getJSON(`/repos/${repo}/activity?days=365&recent=15`);
      } catch (e) {
        if (e.message.includes("404") || e.message.includes("no cached commits") || e.message.includes("POST /analyze first")) {
          console.log("Repository not analyzed yet. Auto-triggering analyze...");
          const parsed = getParsedSettings();
          const res = await postJSON("/analyze", {
            repo,
            refresh: false,
            max_commits: parsed.max_commits,
            top: parsed.top,
          });
          navigate(`/loading?job=${res.job_id}&repo=${repo}&next=/dashboard`);
          return;
        } else {
          throw e;
        }
      }

      const [metaData, qualityData, insightsData] = await Promise.all([
        soft(`/repos/${repo}/meta`),
        soft(`/repos/${repo}/commit-quality`),
        soft(`/repos/${repo}/insights`),
      ]);

      let finalInsights = insightsData;
      if (insightsData.unavailable && insightsData.error && (insightsData.error.includes("404") || insightsData.error.includes("no insights"))) {
        console.log("Insights not found. Auto-triggering insights generation...");
        try {
          const res = await postJSON(`/repos/${repo}/insights`);
          finalInsights = { generating: true, jobId: res.job_id, bullets: ["AI insights are being calculated in the background..."] };
          pollBackgroundInsights(res.job_id);
        } catch (err) {
          console.error("Auto trigger insights failed:", err);
          finalInsights = { unavailable: true, error: String(err) };
        }
      }

      setData({ activity: activityData, meta: metaData, quality: qualityData, insights: finalInsights });
      setLoading(false);
    } catch (e) {
      setError(e.message);
      setLoading(false);
    }
  }, [repo, navigate, getParsedSettings, pollBackgroundInsights]);

  useEffect(() => {
    if (repo) {
      loadData();
    } else {
      setLoading(false);
    }
    return () => {
      clearTimeout(insightsTimerRef.current);
    };
  }, [loadData, repo]);

  const handleReAnalyze = async () => {
    setTriggeringAnalyze(true);
    try {
      const parsed = getParsedSettings();
      const res = await postJSON("/analyze", {
        repo,
        refresh: true,
        max_commits: parsed.max_commits,
        top: parsed.top,
      });
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
      const res = await postJSON("/commit-quality", {
        repo,
        max_commits: parsed.max_commits,
        top: parsed.top,
      });
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
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          insights: { generating: true, jobId: res.job_id, bullets: ["AI insights are being calculated in the background..."] }
        };
      });
      pollBackgroundInsights(res.job_id);
      setTriggeringInsights(false);
    } catch (e) {
      alert(`AI Insights trigger failed: ${e.message}`);
      setTriggeringInsights(false);
    }
  };

  const handleSaveSettings = () => {
    try {
      localStorage.setItem("repolens_config", JSON.stringify(settingsForm));
    } catch (e) {
      console.error("Failed to save config:", e);
    }
    setShowSettings(false);
    handleReAnalyze();
  };

  if (!repo) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface p-6 relative overflow-hidden">
        {/* Ambient background glow */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-primary/5 rounded-full blur-[100px] pointer-events-none"></div>

        <div className="relative w-full max-w-[460px] h-auto p-10 rounded-3xl bg-surface-container-lowest/60 backdrop-blur-xl border border-outline-variant/40 shadow-2xl shadow-primary/10 transition-all duration-300 hover:scale-[1.02] hover:shadow-[0_0_60px_color-mix(in_srgb,var(--color-primary)_20%,transparent)] text-center flex flex-col items-center gap-6">
          <div className="w-20 h-20 rounded-full bg-primary/10 flex items-center justify-center border border-primary/20 shadow-inner">
            <span className="material-symbols-outlined text-primary text-[40px]">link_off</span>
          </div>

          <div className="space-y-3">
            <h2 className="font-display-lg text-3xl text-on-surface font-bold tracking-tight">Missing Link</h2>
            <p className="text-sm text-on-surface-variant leading-relaxed px-2 font-body">
              We need a valid GitHub repository link to analyze the data. Please return to the home page to enter one.
            </p>
          </div>

          <Link
            to="/"
            className="w-full bg-primary hover:bg-primary-container text-on-primary font-code font-bold py-3.5 rounded-xl transition-all duration-300 active:scale-95 text-center flex items-center justify-center gap-2 mt-2 shadow-lg shadow-primary/20 hover:shadow-primary/40"
          >
            <span className="material-symbols-outlined text-[20px]">arrow_back</span>
            <span>Return Home</span>
          </Link>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-[#0e0e0e] text-on-surface">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto"></div>
          <p className="font-code text-label text-on-surface-variant uppercase tracking-widest animate-pulse">
            Loading dashboard data...
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-[#0e0e0e] text-on-surface p-6">
        <div className="max-w-md w-full bg-surface border border-outline-variant p-6 space-y-4 text-center shadow-lg">
          <span className="material-symbols-outlined text-error text-[48px]">warning</span>
          <h2 className="font-code text-heading-lg text-primary">Failed to load Dashboard</h2>
          <p className="text-xs text-on-surface-variant leading-relaxed break-words">{error}</p>
          <button
            onClick={() => navigate("/")}
            className="w-full bg-primary hover:bg-primary-container text-on-primary font-code font-bold py-2 px-4 transition-all rounded-sm"
          >
            RETURN_HOME
          </button>
        </div>
      </div>
    );
  }

  const { activity, meta, quality, insights } = data;
  const hasMeta = meta && !meta.unavailable;
  const hasQuality = quality && !quality.unavailable;
  const hasInsights = insights && !insights.unavailable;

  // Generate 365 Days Grid for Heatmap
  const generateHeatmapGrid = () => {
    const today = new Date();
    const cells = [];
    const heatmapLookup = {};

    if (activity.heatmap) {
      activity.heatmap.forEach((h) => {
        heatmapLookup[h.date] = h.count;
      });
    }

    // Go back 364 days to build a grid of 52 weeks (364 days)
    const startDate = new Date();
    startDate.setDate(today.getDate() - 364);

    // Adjust start date to previous Sunday to align rows perfectly
    const dayOfWeek = startDate.getDay();
    startDate.setDate(startDate.getDate() - dayOfWeek);

    const totalDays = 52 * 7;
    for (let i = 0; i < totalDays; i++) {
      const d = new Date(startDate);
      d.setDate(startDate.getDate() + i);
      const dateStr = d.toISOString().split("T")[0];
      const count = heatmapLookup[dateStr] || 0;
      cells.push({ date: dateStr, count });
    }
    return cells;
  };

  const heatmapCells = generateHeatmapGrid();

  const getHeatmapColor = (count) => {
    if (count === 0) return "bg-surface-container-highest";
    if (count <= 2) return "bg-primary/20";
    if (count <= 5) return "bg-primary/40";
    if (count <= 9) return "bg-primary/70";
    return "bg-primary";
  };

  return (
    <div className="min-h-screen bg-[#0e0e0e] text-on-surface pb-12 font-body">
      {/* Settings Modal Drawer */}
      {showSettings && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4 backdrop-blur-xs">
          <div className="bg-surface border border-outline-variant max-w-sm w-full p-6 shadow-2xl space-y-4">
            <div className="flex justify-between items-center border-b border-outline-variant pb-2">
              <span className="font-code text-label text-primary font-bold">// ANALYSIS_CONFIGURATION</span>
              <button onClick={() => setShowSettings(false)} className="text-on-surface-variant hover:text-primary">
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            <div className="space-y-3 font-code text-xs">
              <div className="space-y-1">
                <label className="text-on-surface-variant">MAX COMMITS TO ANALYZE</label>
                <input
                  type="number"
                  value={settingsForm.maxCommits}
                  onChange={(e) => setSettingsForm({ ...settingsForm, maxCommits: e.target.value })}
                  className="w-full bg-surface-container border border-outline-variant rounded-sm p-2 text-on-surface focus:outline-none focus:border-primary"
                />
              </div>
              <div className="space-y-1">
                <label className="text-on-surface-variant">TOP SCORING HOTSPOTS COUNT</label>
                <input
                  type="number"
                  value={settingsForm.topCount}
                  onChange={(e) => setSettingsForm({ ...settingsForm, topCount: e.target.value })}
                  className="w-full bg-surface-container border border-outline-variant rounded-sm p-2 text-on-surface focus:outline-none focus:border-primary"
                />
              </div>
            </div>
            <button
              onClick={handleSaveSettings}
              className="w-full bg-primary hover:bg-primary-container text-on-primary font-code font-bold py-2 rounded-sm text-xs mt-2"
            >
              SAVE_AND_TRIGGER_ANALYSIS
            </button>
          </div>
        </div>
      )}

      {/* Main Dashboard Content */}
      <main className="pt-6 px-gutter max-w-container-max mx-auto space-y-section-gap">
        {/* Repo Header Section */}
        <section className="pt-4 pb-2">
          <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-6 lg:gap-8">
            <div className="flex-1 space-y-4">
              <div className="flex flex-wrap items-center gap-3 font-code">
                <h1 className="text-heading-lg text-3xl font-bold leading-none tracking-tight">
                  {hasMeta ? meta.full_name : repo}
                </h1>
                {hasMeta && (
                  <div className="flex items-center gap-1.5 px-2.5 py-1 bg-surface-container-high border border-outline-variant/50 rounded-full shadow-sm">
                    <span
                      className="w-2.5 h-2.5 rounded-full"
                      style={{
                        backgroundColor:
                          meta.language === "JavaScript" || meta.language === "TypeScript"
                            ? "#f1e05a"
                            : meta.language === "Python"
                              ? "#3572a5"
                              : meta.language === "Rust"
                                ? "#dea584"
                                : "#8b8b8b",
                      }}
                    ></span>
                    <span className="text-[11px] font-bold text-on-surface-variant leading-none">{meta.language}</span>
                  </div>
                )}
              </div>
              <p className="text-on-surface-variant max-w-2xl text-[14px] leading-relaxed">
                {hasMeta ? meta.description : "Local workspace directory parsed and indexed."}
              </p>

              {hasMeta && (
                <div className="flex flex-wrap items-center gap-4 pt-1">
                  <span className="px-2.5 py-1 bg-surface-container border border-outline-variant/50 text-[11px] uppercase font-bold tracking-wider text-on-surface-variant rounded-md shadow-sm">
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
                className="h-10 px-4 bg-surface-container hover:bg-surface-container-high border border-outline-variant text-on-surface font-code text-[12px] font-bold flex items-center justify-center gap-2 rounded-lg transition-all shadow-sm active:scale-95 disabled:opacity-50"
              >
                <span className="material-symbols-outlined text-[18px]">settings</span>
                CONFIG
              </button>
              <button
                onClick={handleReAnalyze}
                disabled={triggeringAnalyze}
                className="h-10 px-4 bg-surface-container hover:bg-surface-container-high border border-outline-variant text-on-surface font-code text-[12px] font-bold flex items-center justify-center gap-2 rounded-lg transition-all shadow-sm active:scale-95 disabled:opacity-50"
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
                  className="h-10 px-4 bg-surface-container hover:bg-surface-container-high border border-outline-variant text-on-surface font-code text-[12px] font-bold flex items-center justify-center gap-2 rounded-lg transition-all shadow-sm active:scale-95"
                >
                  <span className="material-symbols-outlined text-[18px]">open_in_new</span>
                  GITHUB
                </a>
              )}
            </div>
          </div>
        </section>

        {/* Stats Row */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Card 1: Contributors */}
          <div className="bg-surface-container border border-outline-variant p-4 space-y-1 rounded-sm">
            <p className="text-[10px] text-on-surface-variant font-code uppercase tracking-widest"> CONTRIBUTORS</p>
            <div className="flex items-baseline gap-2">
              <span className="font-stat text-3xl font-bold">{activity.contributors_total}</span>
              <span className="text-label text-primary">active authors</span>
            </div>
            <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
              <div className="bg-primary h-full w-[60%]"></div>
            </div>
          </div>

          {/* Card 2: Total Commits */}
          <div className="bg-surface-container border border-outline-variant p-4 space-y-1 rounded-sm">
            <p className="text-[10px] text-on-surface-variant font-code uppercase tracking-widest">TOTAL COMMITS</p>
            <div className="flex items-baseline gap-2">
              <span className="font-stat text-3xl font-bold">{formatNumber(activity.total_commits)}</span>
              <span className="text-label text-on-surface-variant">historical</span>
            </div>
            <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
              <div className="bg-primary h-full w-[85%]"></div>
            </div>
          </div>

          {/* Card 3: Open Issues */}
          <div className="bg-surface-container border border-outline-variant p-4 space-y-1 rounded-sm">
            <p className="text-[10px] text-on-surface-variant font-code uppercase tracking-widest">OPEN ISSUES</p>
            <div className="flex items-baseline gap-2">
              <span className="font-stat text-3xl font-bold">
                {hasMeta ? formatNumber(meta.open_issues) : "N/A"}
              </span>
              <span className={`text-label ${hasMeta && meta.open_issues > 0 ? "text-error" : "text-on-surface-variant"}`}>
                {hasMeta && meta.open_issues > 0 ? "▲ active" : "stable"}
              </span>
            </div>
            <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
              <div className={`h-full ${hasMeta && meta.open_issues > 0 ? "bg-error" : "bg-primary"} w-[25%]`}></div>
            </div>
          </div>

          {/* Card 4: Health Score */}
          <div className="relative bg-surface-container border border-outline-variant p-4 space-y-1 rounded-sm group cursor-help">
            <p className="text-[10px] text-on-surface-variant font-code uppercase tracking-widest flex justify-between">
              <span>HEALTH SCORE</span>
              <span className="material-symbols-outlined text-xs">info</span>
            </p>
            <div className="flex items-baseline gap-2">
              <span className="font-stat text-3xl font-bold text-primary">
                {activity.health.score !== null ? activity.health.score.toFixed(1) : "N/A"}
              </span>
              <span className="text-label text-primary">▲ stable</span>
            </div>
            <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
              <div
                className="bg-primary h-full"
                style={{ width: `${(activity.health.score || 0) * 10}%` }}
              ></div>
            </div>

            {/* Custom Tooltip */}
            <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-64 bg-surface-container-highest border border-outline-variant p-3 text-xs opacity-0 group-hover:opacity-100 transition-opacity duration-200 z-30 pointer-events-none rounded-sm shadow-xl font-code space-y-1.5">
              <p className="text-primary font-bold">Transparency Index Formula:</p>
              <p className="text-on-surface-variant text-[10px] leading-relaxed">
                {activity.health.formula || "Stability formula unresolved."}
              </p>
              <div className="grid grid-cols-2 gap-2 text-[10px] pt-1.5 border-t border-outline-variant/30 text-on-surface-variant">
                <div>stability: {activity.health.stability?.toFixed(1) || "10.0"}</div>
                <div>quality: {activity.health.commit_quality?.toFixed(1) || "N/A"}</div>
              </div>
            </div>
          </div>
        </section>

        {/* Heatmap Section */}
        <section className="bg-surface-container border border-outline-variant p-6 overflow-x-auto scrollbar-thin rounded-xl shadow-sm">
          <div className="flex justify-between items-center mb-6 min-w-[800px]">
            <p className="text-[11px] text-on-surface-variant font-code font-bold uppercase tracking-widest"> ANNUAL CONTRIBUTION VELOCITY</p>
            <div className="flex items-center gap-3 font-code text-[11px] text-on-surface-variant">
              <span>Less</span>
              <div className="flex gap-1">
                <div className="w-[13px] h-[13px] bg-surface-container-highest border border-outline-variant/30 rounded-sm shadow-inner"></div>
                <div className="w-[13px] h-[13px] bg-primary/20 rounded-sm shadow-inner"></div>
                <div className="w-[13px] h-[13px] bg-primary/40 rounded-sm shadow-inner"></div>
                <div className="w-[13px] h-[13px] bg-primary/70 rounded-sm shadow-inner"></div>
                <div className="w-[13px] h-[13px] bg-primary rounded-sm shadow-inner"></div>
              </div>
              <span>More</span>
            </div>
          </div>

          <div className="min-w-[800px] flex gap-3">
            {/* Days of week labels */}
            <div className="grid grid-rows-7 gap-1 text-[10px] text-on-surface-variant/70 font-code pr-1 select-none h-[115px] items-center">
              <span className="leading-none flex items-center h-[13px]">Sun</span>
              <span className="leading-none flex items-center h-[13px]">Mon</span>
              <span className="leading-none flex items-center h-[13px]">Tue</span>
              <span className="leading-none flex items-center h-[13px]">Wed</span>
              <span className="leading-none flex items-center h-[13px]">Thu</span>
              <span className="leading-none flex items-center h-[13px]">Fri</span>
              <span className="leading-none flex items-center h-[13px]">Sat</span>
            </div>

            {/* Grid */}
            <div className="flex-grow grid grid-flow-col grid-rows-7 gap-1 h-[115px]">
              {heatmapCells.map((cell, idx) => (
                <div
                  key={idx}
                  title={`${cell.date}: ${cell.count} commits`}
                  className={`w-[13px] h-[13px] rounded-[3px] transition-all duration-200 hover:ring-2 hover:ring-primary/60 cursor-crosshair ${getHeatmapColor(cell.count)} ${cell.count === 0 ? "border border-outline-variant/30 shadow-inner" : "shadow-sm"}`}
                ></div>
              ))}
            </div>
          </div>
        </section>

        {/* Two Column Content */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column (Contributors / Commits) */}
          <div className="lg:col-span-7 space-y-6">
            {/* Top Contributors */}
            <div className="bg-surface-container border border-outline-variant rounded-sm overflow-hidden">
              <div className="p-4 border-b border-outline-variant flex justify-between items-center">
                <p className="text-[10px] text-on-surface-variant font-code font-bold uppercase tracking-widest"> TOP CONTRIBUTORS</p>
                <span className="text-[10px] font-code text-on-surface-variant uppercase">{activity.contributors.length} indexed</span>
              </div>
              <div className="divide-y divide-outline-variant max-h-[360px] overflow-y-auto pr-1 scrollbar-thin">
                {activity.contributors.map((c) => (
                  <div key={c.author} className="p-3.5 flex items-center gap-4 hover:bg-surface-container-high transition-colors group">
                    <div className="w-8 h-8 rounded-sm bg-surface-container-highest flex items-center justify-center font-code font-bold text-xs border border-outline-variant/30 select-none">
                      {c.author.slice(0, 2).toUpperCase()}
                    </div>
                    <div className="flex-grow space-y-1">
                      <div className="flex justify-between items-baseline">
                        <span className="font-code text-code text-on-surface group-hover:text-primary transition-colors">
                          {c.author}
                        </span>
                        <span className="text-[10px] text-on-surface-variant font-code">
                          {c.commits} commits ({Math.round(c.share * 100)}%)
                        </span>
                      </div>
                      <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
                        <div
                          className="bg-primary h-full transition-all duration-500"
                          style={{ width: `${c.share * 100}%` }}
                        ></div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Recent Commits */}
            <div className="bg-surface-container border border-outline-variant rounded-sm overflow-hidden">
              <div className="p-4 border-b border-outline-variant flex justify-between items-center">
                <p className="text-[10px] text-on-surface-variant font-code font-bold uppercase tracking-widest"> RECENT COMMITS ACTIVITY</p>
                <span className="text-[10px] font-code text-on-surface-variant uppercase">recent {activity.recent_commits.length}</span>
              </div>
              <div className="divide-y divide-outline-variant">
                {activity.recent_commits.map((c) => (
                  <div key={c.sha} className="p-3 flex items-start justify-between gap-4 hover:bg-surface-container-high transition-colors">
                    <div className="space-y-1 flex-grow">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-code text-code text-on-surface font-medium leading-tight">
                          {c.subject}
                        </span>
                        {c.is_bugfix && (
                          <span className="px-1.5 py-0.5 rounded-[2px] bg-error-container/20 border border-error-container/50 text-error text-[8px] font-code uppercase select-none">
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
                    <span className="font-code text-[11px] text-primary/70 bg-surface-container-highest px-2 py-0.5 border border-outline-variant/30 select-all rounded-sm shrink-0">
                      {c.sha.slice(0, 7)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right Column (Insights / Quality / Languages) */}
          <div className="lg:col-span-5 space-y-6">
            {/* AI Insights Card */}
            <div className="bg-surface-container border border-outline-variant rounded-sm p-4 space-y-4">
              <div className="flex items-center justify-between border-b border-outline-variant pb-2">
                <p className="text-[10px] text-on-surface-variant font-code font-bold uppercase tracking-widest flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-sm text-primary">auto_awesome</span>
                  AI Repo Insights
                </p>
                {hasInsights && (
                  <span className="text-[9px] font-code text-on-surface-variant opacity-60">
                    provider: {insights.provider?.split(" (")[0] || "LLM"}
                  </span>
                )}
              </div>

              {!hasInsights ? (
                <div className="text-center py-6 space-y-3 font-code">
                  <p className="text-xs text-on-surface-variant">AI Insights report not found for this repository.</p>
                  <button
                    onClick={handleTriggerInsights}
                    disabled={triggeringInsights}
                    className="bg-primary hover:bg-primary-container text-on-primary text-[10px] font-bold px-4 py-2 rounded-sm cursor-pointer disabled:opacity-50"
                  >
                    {triggeringInsights ? "GENERATING..." : "GENERATE AI INSIGHTS"}
                  </button>
                  {insights?.error && (
                    <p className="text-[10px] text-error bg-error-container/10 border border-error-container/20 p-2 rounded-[2px] leading-relaxed">
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
                    <div className="flex items-center gap-2 text-[10px] text-primary/80 font-code animate-pulse pt-2.5">
                      <span className="w-1.5 h-1.5 bg-primary rounded-full animate-ping"></span>
                      <span>Calculating AI profiles...</span>
                    </div>
                  )}
                  {insights.generated_at && (
                    <div className="pt-2 flex justify-between items-center text-[9px] text-on-surface-variant/50 font-code border-t border-outline-variant/30 mt-2">
                      <span>GENERATED: {timeAgo(insights.generated_at)}</span>
                      <button
                        onClick={handleTriggerInsights}
                        disabled={triggeringInsights}
                        className="hover:text-primary transition-colors uppercase cursor-pointer"
                      >
                        {triggeringInsights ? "REBUILDING..." : "REBUILD"}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Commit Quality Card */}
            <div className="bg-surface-container border border-outline-variant rounded-sm p-4 space-y-4">
              <div className="flex items-center justify-between border-b border-outline-variant pb-2">
                <p className="text-[10px] text-on-surface-variant font-code font-bold uppercase tracking-widest flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-sm text-primary">verified_user</span>
                  Commit Quality
                </p>
                {hasQuality && (
                  <span className="text-[9px] font-code text-on-surface-variant opacity-60">
                    score: {quality.avg_score?.toFixed(2)}/10
                  </span>
                )}
              </div>

              {!hasQuality ? (
                <div className="text-center py-6 space-y-3 font-code">
                  <p className="text-xs text-on-surface-variant">Quality diagnostics not calculated yet.</p>
                  <button
                    onClick={handleTriggerQuality}
                    disabled={triggeringQuality}
                    className="bg-primary hover:bg-primary-container text-on-primary text-[10px] font-bold px-4 py-2 rounded-sm cursor-pointer disabled:opacity-50"
                  >
                    {triggeringQuality ? "GENERATING..." : "RUN QUALITY ANALYSIS"}
                  </button>
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Score breakdown metrics */}
                  <div className="grid grid-cols-2 gap-3 text-xs font-code">
                    <div className="p-2 bg-surface-container-high border border-outline-variant/30 rounded-sm">
                      <span className="text-[10px] text-on-surface-variant block uppercase font-bold">AVG_SCORE</span>
                      <span className="text-lg font-bold text-primary mt-0.5 block">
                        {quality.avg_score?.toFixed(1)}/10
                      </span>
                    </div>
                    <div className="p-2 bg-surface-container-high border border-outline-variant/30 rounded-sm">
                      <span className="text-[10px] text-on-surface-variant block uppercase font-bold text-error">WEAK_COMMITS</span>
                      <span className="text-lg font-bold text-error mt-0.5 block">
                        {quality.weak} / {quality.commits}
                      </span>
                    </div>
                    <div className="p-2 bg-surface-container-high border border-outline-variant/30 rounded-sm">
                      <span className="text-[10px] text-on-surface-variant block uppercase font-bold">IMPERATIVE VERBS</span>
                      <span className="text-lg font-bold mt-0.5 block">
                        {quality.pct_imperative}%
                      </span>
                    </div>
                    <div className="p-2 bg-surface-container-high border border-outline-variant/30 rounded-sm">
                      <span className="text-[10px] text-on-surface-variant block uppercase font-bold">ISSUE REFERENCES</span>
                      <span className="text-lg font-bold mt-0.5 block">
                        {quality.pct_referenced}%
                      </span>
                    </div>
                  </div>

                  {/* Trend chart using Recharts */}
                  {quality.trend && quality.trend.length > 0 && (
                    <div className="space-y-1.5">
                      <span className="font-code text-[9px] text-on-surface-variant uppercase tracking-wider block font-bold">// QUALITY TREND</span>
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
                            <Line
                              type="monotone"
                              dataKey="avg_score"
                              stroke="#ffb77d"
                              strokeWidth={2}
                              dot={false}
                            />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  )}

                  {/* Common issues */}
                  {quality.common_issues && quality.common_issues.length > 0 && (
                    <div className="space-y-1.5 font-code">
                      <span className="text-[9px] text-on-surface-variant uppercase tracking-wider block font-bold">// COMMON DIAGNOSTICS</span>
                      <div className="flex flex-wrap gap-1.5">
                        {quality.common_issues.slice(0, 5).map(([issue, count]) => (
                          <span key={issue} className="px-2 py-0.5 bg-surface-container-lowest text-[10px] border border-outline-variant/40 text-on-surface-variant hover:border-primary transition-colors cursor-default rounded-sm">
                            {issue}: {count}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Worst commits */}
                  {quality.worst && quality.worst.length > 0 && (
                    <div className="space-y-2 font-code">
                      <span className="text-[9px] text-on-surface-variant uppercase tracking-wider block font-bold">// WORST COMMITS MATRIX</span>
                      <div className="divide-y divide-outline-variant/50 max-h-[140px] overflow-y-auto pr-1 scrollbar-thin bg-black/20 p-2 rounded-sm border border-outline-variant/20">
                        {quality.worst.slice(0, 3).map((wc) => (
                          <div key={wc.sha} className="py-1.5 first:pt-0 last:pb-0 text-[11px] leading-tight space-y-0.5">
                            <div className="flex justify-between items-start gap-2">
                              <span className="text-on-surface font-medium">{wc.subject}</span>
                              <span className="text-error font-bold shrink-0">{wc.score}/10</span>
                            </div>
                            <div className="text-[9px] text-on-surface-variant/50 flex gap-2">
                              <span>sha: {wc.sha.slice(0, 7)}</span>
                              <span>•</span>
                              <span>author: {wc.author}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Footer stats */}
                  <div className="pt-2 flex justify-between items-center text-[9px] text-on-surface-variant/50 font-code border-t border-outline-variant/30">
                    <span>CALCULATED: {timeAgo(quality.generated_at)}</span>
                    <button
                      onClick={handleTriggerQuality}
                      disabled={triggeringQuality}
                      className="hover:text-primary transition-colors uppercase cursor-pointer"
                    >
                      {triggeringQuality ? "RE-RUNNING..." : "RE-RUN"}
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Languages donut/bars card */}
            {hasMeta && meta.languages && meta.languages.length > 0 && (
              <div className="bg-surface-container border border-outline-variant rounded-sm p-4 space-y-3">
                <p className="text-[10px] text-on-surface-variant font-code font-bold uppercase tracking-widest border-b border-outline-variant pb-2">LANGUAGE INVENTORY</p>
                <div className="space-y-2.5 pt-1">
                  {meta.languages.slice(0, 4).map((lang) => (
                    <div key={lang.name} className="space-y-1">
                      <div className="flex justify-between text-xs font-code">
                        <span className="text-on-surface">{lang.name}</span>
                        <span className="text-on-surface-variant">{lang.pct.toFixed(1)}%</span>
                      </div>
                      <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-primary"
                          style={{ width: `${lang.pct}%` }}
                        ></div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
