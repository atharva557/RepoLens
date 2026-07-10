import { useEffect, useState, useCallback } from "react";
import { useNavigate, Link } from "react-router-dom";
import { getJSON, postJSON } from "../lib/api";


function formatNumber(num) {
  if (num === undefined || num === null) return "0";
  if (num >= 1000) return (num / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  return num.toString();
}

export default function DeveloperProfile() {
  const navigate = useNavigate();
  const searchParams = new URLSearchParams(window.location.search);
  const repoParam = searchParams.get("repo");
  let userParam = searchParams.get("user");

  if (!userParam && repoParam) {
    let cleaned = repoParam.trim();
    if (cleaned.includes("github.com/")) {
      const parts = cleaned.split("github.com/");
      if (parts.length > 1) {
        const pathParts = parts[1].split("/");
        if (pathParts.length >= 1) userParam = pathParts[0];
      }
    } else {
      const parts = cleaned.split("/");
      if (parts.length > 0) userParam = parts[0];
    }
  }
  const user = userParam;

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [triggeringBuild, setTriggeringBuild] = useState(false);
  const [tokenError, setTokenError] = useState(false);
  const [gaugeAnimated, setGaugeAnimated] = useState(false);
  const [selectedYear, setSelectedYear] = useState(() => new Date().getFullYear());

  const loadProfile = useCallback(() => {
    setLoading(true);
    setError(null);
    setTokenError(false);
    getJSON(`/profiles/${user}`)
      .then((profileData) => {
        setData(profileData);
        setLoading(false);
        setTimeout(() => setGaugeAnimated(true), 100);
      })
      .catch(async (e) => {
        const msg = String(e);
        if (msg.includes("404") || msg.includes("no profile") || msg.includes("POST /profiles")) {
          setTriggeringBuild(true);
          try {
            const res = await postJSON(`/profiles/${user}`);
            navigate(`/loading?job=${res.job_id}&user=${user}&next=/profile`);
          } catch (postErr) {
            const pmsg = String(postErr);
            if (pmsg.includes("400") || pmsg.includes("token") || pmsg.includes("TOKEN")) {
              setTokenError(true);
            }
            setError(pmsg);
            setTriggeringBuild(false);
            setLoading(false);
          }
        } else {
          setError(msg);
          setLoading(false);
        }
      });
  }, [user, navigate]);

  useEffect(() => {
    if (user) {
      loadProfile();
    } else {
      setLoading(false);
    }
  }, [loadProfile, user]);

  useEffect(() => {
    if (data?.heatmap && data.heatmap.length > 0) {
      const years = data.heatmap
        .map(h => parseInt(h.date.split("-")[0], 10))
        .filter(yr => !isNaN(yr));
      if (years.length > 0) {
        setSelectedYear(Math.max(...years));
      }
    }
  }, [data]);

  const handleBuildProfile = async () => {
    setTriggeringBuild(true);
    setTokenError(false);
    try {
      const res = await postJSON(`/profiles/${user}`);
      navigate(`/loading?job=${res.job_id}&user=${user}&next=/profile`);
    } catch (e) {
      if (e.message.includes("400") || e.message.includes("TOKEN") || e.message.includes("token")) {
        setTokenError(true);
      } else {
        alert(`Failed to trigger profile: ${e.message}`);
      }
      setTriggeringBuild(false);
    }
  };

  if (!user) {
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
              We need a valid GitHub username to analyze the profile. Please return to the home page to enter one.
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
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto"></div>
          <p className="font-code-sm text-on-surface-variant uppercase tracking-widest animate-pulse">
            Retrieving developer profile...
          </p>
        </div>
      </div>
    );
  }

  if (error && (error.includes("404") || error.includes("not found"))) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="glass-panel p-8 text-center space-y-6 rounded-xl max-w-md w-full">
          <span className="material-symbols-outlined text-primary text-[64px]">person_off</span>
          <div className="space-y-2">
            <h2 className="font-headline-lg text-primary font-bold">Profile Not Found</h2>
            <p className="font-body-sm text-on-surface-variant leading-relaxed">
              No developer profile index found for <span className="text-on-surface font-bold">@{user}</span>.
            </p>
          </div>
          {tokenError && (
            <div className="p-sm bg-error-container/20 border border-error-container/50 text-error rounded-lg text-left font-body-sm">
              <p className="font-bold flex items-center gap-1 mb-1"><span className="material-symbols-outlined text-sm">warning</span> ACCESS DENIED</p>
              <p>The server lacks a GitHub API Token. Rebuilding profiles requires GITHUB_TOKEN.</p>
            </div>
          )}
          <div className="space-y-3 pt-2">
            <button
              onClick={handleBuildProfile}
              disabled={triggeringBuild}
              className="w-full bg-primary text-on-primary font-label-caps py-sm rounded-lg hover:shadow-[0_0_15px_rgba(99,102,241,0.5)] transition-all disabled:opacity-50"
            >
              {triggeringBuild ? "BUILDING PIPELINE..." : `BUILD @${user} PROFILE`}
            </button>
            <button
              onClick={() => navigate("/")}
              className="w-full border border-outline-variant hover:bg-surface-container-low text-on-surface-variant font-label-caps py-sm rounded-lg transition-colors"
            >
              RETURN HOME
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="glass-panel p-8 text-center space-y-4 rounded-xl max-w-md w-full">
          <span className="material-symbols-outlined text-error text-[54px]">warning</span>
          <h2 className="font-headline-lg text-error font-bold">Error loading profile</h2>
          <p className="font-body-sm text-on-surface-variant leading-relaxed break-words">{error}</p>
          <button
            onClick={loadProfile}
            className="w-full bg-primary text-on-primary font-label-caps py-sm rounded-lg"
          >
            RETRY
          </button>
        </div>
      </div>
    );
  }

  const social = data.user || {};
  const hasSocial = Object.keys(social).length > 0;
  const lquality = data.commit_message_quality || 0;
  const lqualityPct = Math.round(lquality * 10);

  const availableYears = (() => {
    const heatmapData = data?.heatmap || [];
    const yearsSet = new Set();
    heatmapData.forEach(h => {
      if (h.date) {
        const yr = parseInt(h.date.split("-")[0], 10);
        if (!isNaN(yr)) yearsSet.add(yr);
      }
    });
    yearsSet.add(new Date().getFullYear());
    return Array.from(yearsSet).sort((a, b) => b - a);
  })();

  const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

  // Heatmap generation
  const generateHeatmapGrid = () => {
    const cells = [];
    const heatmapLookup = {};
    if (data.heatmap) {
      data.heatmap.forEach((h) => {
        heatmapLookup[h.date] = h.count;
      });
    }

    const jan1 = new Date(Date.UTC(selectedYear, 0, 1));
    const startPadding = jan1.getUTCDay();

    // Start padding
    for (let i = 0; i < startPadding; i++) {
      cells.push({
        isPadding: true,
        row: i,
        column: 0
      });
    }

    // Days of the year
    let current = new Date(Date.UTC(selectedYear, 0, 1));
    while (current.getUTCFullYear() === selectedYear) {
      const dateStr = current.toISOString().split("T")[0];
      const count = heatmapLookup[dateStr] || 0;
      const dayOfWeek = current.getUTCDay();
      const cellIndex = cells.length;
      const col = Math.floor(cellIndex / 7);

      cells.push({
        date: dateStr,
        count,
        dayOfWeek,
        row: dayOfWeek,
        column: col,
        isPadding: false,
        title: `${dateStr} (${WEEKDAYS[dayOfWeek]}): ${count} commit${count === 1 ? "" : "s"}`
      });

      current.setUTCDate(current.getUTCDate() + 1);
    }

    // End padding
    const lastCell = cells[cells.length - 1];
    const lastDayOfWeek = lastCell ? lastCell.dayOfWeek : 6;
    const endPadding = 6 - lastDayOfWeek;
    for (let i = 0; i < endPadding; i++) {
      const cellIndex = cells.length;
      const col = Math.floor(cellIndex / 7);
      cells.push({
        isPadding: true,
        row: (lastDayOfWeek + 1 + i) % 7,
        column: col
      });
    }

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
            const monthName = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][month];
            labels.push({ text: monthName, colIndex });
            lastColIndex = colIndex;
          }
          lastMonth = month;
        }
      }
    });
    return labels;
  };

  const monthLabels = getMonthLabels(heatmapCells);

  const getHeatmapColor = (count) => {
    if (count === 0) return "bg-[#111111]";
    if (count <= 2) return "bg-primary/20";
    if (count <= 5) return "bg-primary/40";
    if (count <= 9) return "bg-primary/70";
    return "bg-primary";
  };

  const activityColors = [
    { text: "text-primary", bg: "bg-primary" },
    { text: "text-secondary", bg: "bg-secondary" },
    { text: "text-tertiary", bg: "bg-tertiary" },
    { text: "text-on-surface", bg: "bg-on-surface" },
    { text: "text-error", bg: "bg-error" },
    { text: "text-outline", bg: "bg-outline" },
  ];

  const topLanguage = data.languages && data.languages.length > 0 ? data.languages[0] : null;

  return (
    <div className="min-h-screen overflow-x-hidden">
      {/* TopNavBar */}
      <nav className="fixed top-0 left-0 w-full z-50 flex justify-between items-center px-margin-desktop py-4 bg-[#1a1a1a]/80 backdrop-blur-xl border-b border-outline-variant/20 shadow-sm">
        <div className="flex items-center gap-lg">
          <span className="font-display-lg text-display-lg font-bold bg-gradient-to-r from-primary to-secondary bg-clip-text text-transparent">RepoLens</span>
          <div className="hidden md:flex gap-md items-center">
            <Link className="font-body-lg text-body-lg text-on-surface-variant font-medium hover:text-primary transition-colors duration-200" to={`/dashboard${repoParam ? `?repo=${repoParam}` : ''}`}>Dashboard</Link>
            <Link className="font-body-lg text-body-lg text-on-surface-variant font-medium hover:text-primary transition-colors duration-200" to={`/hotspots${repoParam ? `?repo=${repoParam}` : ''}`}>Bug Hotspots</Link>
            <Link className="font-body-lg text-body-lg text-primary font-bold border-b-2 border-primary pb-1" to={`/profile${repoParam ? `?repo=${repoParam}` : ''}`}>Developer Profile</Link>
          </div>
        </div>
        <div className="flex items-center gap-md">
          <button className="text-on-surface-variant hover:text-primary transition-colors">
            <span className="material-symbols-outlined">notifications</span>
          </button>
          <div className="w-10 h-10 rounded-full overflow-hidden border border-outline-variant/20">
            {hasSocial && social.avatar_url ? (
              <img className="w-full h-full object-cover" src={social.avatar_url} alt="Profile" />
            ) : (
              <div className="w-full h-full flex items-center justify-center bg-primary/20 text-primary font-bold">{data.username.slice(0, 2).toUpperCase()}</div>
            )}
          </div>
        </div>
      </nav>

      <main className="mt-xl pt-lg pb-xl px-margin-mobile md:px-margin-desktop max-w-[1440px] mx-auto">
        {/* Profile Header */}
        <section className="glass-panel p-md rounded-xl mb-lg flex flex-col md:flex-row gap-lg items-center md:items-start relative overflow-hidden">
          <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary via-secondary to-tertiary"></div>
          <div className="relative shrink-0">
            <div className="w-32 h-32 rounded-xl overflow-hidden border-2 border-primary/20 shadow-xl">
              {hasSocial && social.avatar_url ? (
                <img className="w-full h-full object-cover" src={social.avatar_url} alt="Profile" />
              ) : (
                <div className="w-full h-full flex items-center justify-center bg-primary/20 text-primary font-display-lg text-4xl font-bold">{data.username.slice(0, 2).toUpperCase()}</div>
              )}
            </div>
            <div className="absolute -bottom-2 -right-2 bg-surface border border-outline-variant p-1 rounded-lg">
              <span className="material-symbols-outlined text-primary text-sm">verified</span>
            </div>
          </div>

          <div className="flex-grow text-center md:text-left">
            <div className="flex flex-col md:flex-row md:items-end gap-sm mb-xs">
              <h1 className="font-display-lg text-display-lg leading-none">Developer Profile: @{user}</h1>
              <span className="px-3 py-1 rounded-full bg-secondary/10 border border-secondary/20 text-secondary font-label-caps uppercase">
                {data.primary_type || "Not Available"}
              </span>
            </div>
            <p className="font-body-lg text-on-surface-variant mb-md max-w-2xl">
              {social.bio || `${user} is an elite contributor profiled on RepoLens. Analyzing obsidian-grade software systems and high-density technical solutions.`}
            </p>
            <div className="flex flex-wrap justify-center md:justify-start gap-lg">
              <div className="flex flex-col">
                <span className="font-headline-md text-headline-md text-primary">{formatNumber(social.followers)}</span>
                <span className="font-label-caps text-on-surface-variant">Followers</span>
              </div>
              <div className="flex flex-col">
                <span className="font-headline-md text-headline-md text-primary">{formatNumber(social.following)}</span>
                <span className="font-label-caps text-on-surface-variant">Following</span>
              </div>
              <div className="flex flex-col">
                <span className="font-headline-md text-headline-md text-primary">{formatNumber(social.public_repos)}</span>
                <span className="font-label-caps text-on-surface-variant">Repositories</span>
              </div>
            </div>
          </div>

          <div className="flex gap-sm">
            <button
              onClick={handleBuildProfile}
              disabled={triggeringBuild}
              className="bg-gradient-to-r from-primary to-secondary text-on-primary font-label-caps px-lg py-sm rounded-lg hover:shadow-[0_0_15px_rgba(99,102,241,0.5)] transition-all disabled:opacity-50"
            >
              {triggeringBuild ? "SYNCING..." : "SYNC INDEX"}
            </button>
            <button className="border border-outline-variant hover:bg-surface-container-low transition-colors p-sm rounded-lg">
              <span className="material-symbols-outlined">mail</span>
            </button>
          </div>
        </section>

        {/* Bento Grid Section */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-gutter">
          {/* Quick Stats */}
          <div className="md:col-span-12 grid grid-cols-2 lg:grid-cols-4 gap-gutter">
            <div className="glass-panel p-md rounded-xl flex flex-col justify-between">
              <span className="font-label-caps text-on-surface-variant mb-sm">Analyzed Commits</span>
              <div className="flex items-end justify-between">
                <span className="font-display-lg text-display-lg text-primary leading-none">{formatNumber(data.commits_analyzed)}</span>
                <span className="text-tertiary font-body-sm flex items-center"><span className="material-symbols-outlined text-sm">trending_up</span> Profiler</span>
              </div>
            </div>
            <div className="glass-panel p-md rounded-xl flex flex-col justify-between">
              <span className="font-label-caps text-on-surface-variant mb-sm">PRs Merged</span>
              <div className="flex items-end justify-between">
                <span className="font-display-lg text-display-lg text-secondary leading-none">{formatNumber(data.prs_merged)}</span>
                <span className="text-tertiary font-body-sm flex items-center"><span className="material-symbols-outlined text-sm">trending_up</span> out of {data.authored_prs || 0}</span>
              </div>
            </div>
            <div className="glass-panel p-md rounded-xl flex flex-col justify-between">
              <span className="font-label-caps text-on-surface-variant mb-sm">Issues Resolved</span>
              <div className="flex items-end justify-between">
                <span className="font-display-lg text-display-lg text-tertiary leading-none">{formatNumber(data.issues_resolved)}</span>
                <span className="text-on-surface-variant font-body-sm">Verified</span>
              </div>
            </div>
            <div className="glass-panel p-md rounded-xl flex flex-col justify-between">
              <span className="font-label-caps text-on-surface-variant mb-sm">Years Active</span>
              <div className="flex items-end justify-between">
                <span className="font-display-lg text-display-lg text-on-surface leading-none">{social.years_active?.toFixed(1) || "1.0"}</span>
                <span className="text-on-surface-variant font-body-sm">Experience</span>
              </div>
            </div>
          </div>

          {/* Heatmap */}
          <div className="md:col-span-8 glass-panel rounded-xl overflow-hidden flex flex-col">
            <div className="terminal-header px-md py-sm flex items-center justify-between">
              <div className="flex gap-2">
                <div className="dot"></div><div className="dot"></div><div className="dot"></div>
              </div>
              <span className="font-code-sm text-on-surface-variant">contribution_matrix.sh</span>
            </div>
            <div className="p-md">
              <div className="flex justify-between items-center mb-md">
                <h3 className="font-headline-md text-headline-md">Annual Velocity</h3>
                {availableYears.length > 0 && (
                  <select
                    value={selectedYear}
                    onChange={(e) => setSelectedYear(parseInt(e.target.value, 10))}
                    className="bg-[#111111] border border-outline-variant/30 text-on-surface text-xs font-code rounded px-2 py-0.5 outline-none cursor-pointer focus:ring-1 focus:ring-primary"
                  >
                    {availableYears.map((yr) => (
                      <option key={yr} value={yr}>
                        {yr}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <div className="flex flex-col overflow-x-auto pb-4">
                {/* Month labels */}
                <div className="flex gap-2 mb-1.5 min-w-[700px]">
                  <div className="w-[20px] shrink-0"></div>
                  <div className="flex-grow grid grid-flow-col gap-1 text-[8px] text-on-surface-variant/70 font-code select-none">
                    {Array.from({ length: totalColumns }).map((_, colIdx) => {
                      const label = monthLabels.find(l => l.colIndex === colIdx);
                      return (
                        <span key={colIdx} className="w-[12px] overflow-visible whitespace-nowrap text-left leading-none">
                          {label ? label.text : ""}
                        </span>
                      );
                    })}
                  </div>
                </div>

                <div className="flex gap-2 min-w-[700px]">
                  {/* Days of week labels */}
                  <div className="w-[20px] grid grid-rows-7 gap-1 text-[8px] text-on-surface-variant/70 font-code select-none h-[108px] items-center text-right pr-1 shrink-0">
                    <span className="leading-none">Sun</span>
                    <span className="leading-none">Mon</span>
                    <span className="leading-none">Tue</span>
                    <span className="leading-none">Wed</span>
                    <span className="leading-none">Thu</span>
                    <span className="leading-none">Fri</span>
                    <span className="leading-none">Sat</span>
                  </div>

                  {/* Grid */}
                  <div className="flex-grow grid grid-flow-col grid-rows-7 gap-1 h-[108px]">
                    {heatmapCells.map((cell, idx) => {
                      if (cell.isPadding) {
                        return (
                          <div
                            key={idx}
                            className="w-[12px] h-[12px] opacity-0 pointer-events-none"
                          ></div>
                        );
                      }
                      return (
                        <div
                          key={idx}
                          title={cell.title}
                          className={`contribution-cell ${getHeatmapColor(cell.count)} transition-all duration-200 hover:ring-2 hover:ring-primary/60 cursor-crosshair`}
                        ></div>
                      );
                    })}
                  </div>
                </div>
              </div>

              <div className="flex justify-between items-center mt-sm text-on-surface-variant font-label-caps">
                <span>Less Activity</span>
                <div className="flex gap-1">
                  <div className="contribution-cell bg-[#111111]"></div>
                  <div className="contribution-cell bg-primary/20"></div>
                  <div className="contribution-cell bg-primary/40"></div>
                  <div className="contribution-cell bg-primary/70"></div>
                  <div className="contribution-cell bg-primary"></div>
                </div>
                <span>More Activity</span>
              </div>
            </div>
          </div>

          {/* Language Circular Chart */}
          <div className="md:col-span-4 glass-panel p-md rounded-xl flex flex-col items-center justify-center text-center">
            <h3 className="font-headline-md text-headline-md mb-lg">Top Languages</h3>
            {topLanguage ? (
              <>
                <div
                  className="relative w-40 h-40 radial-progress rounded-full flex items-center justify-center mb-lg"
                  style={{ background: `radial-gradient(closest-side, #111111 79%, transparent 80% 100%), conic-gradient(#c0c1ff ${Math.round(topLanguage.pct)}%, #222222 0)` }}
                >
                  <div className="flex flex-col">
                    <span className="font-headline-lg text-headline-lg">{topLanguage.name}</span>
                    <span className="font-label-caps text-on-surface-variant">{Math.round(topLanguage.pct)}% Usage</span>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-md w-full">
                  {data.languages.slice(0, 4).map((lang, idx) => {
                    const bgColors = ["bg-primary", "bg-secondary", "bg-tertiary", "bg-outline"];
                    return (
                      <div key={lang.name} className="flex items-center gap-sm">
                        <div className={`w-3 h-3 rounded-full ${bgColors[idx % bgColors.length]}`}></div>
                        <span className="font-body-sm truncate">{lang.name}</span>
                      </div>
                    );
                  })}
                </div>
              </>
            ) : (
              <div className="text-on-surface-variant font-body-sm py-8">No language data</div>
            )}
          </div>

          {/* Activity Split */}
          <div className="md:col-span-6 glass-panel p-md rounded-xl">
            <h3 className="font-headline-md text-headline-md mb-lg">Contribution Mix</h3>
            <div className="space-y-lg">
              {Object.entries(data.activity_split || {}).map(([key, value], idx) => {
                const col = activityColors[idx % activityColors.length];
                return (
                  <div key={key}>
                    <div className="flex justify-between mb-2">
                      <span className="font-body-lg">{key}</span>
                      <span className={col.text}>{Math.round(value)}%</span>
                    </div>
                    <div className="w-full h-2 bg-surface-container rounded-full overflow-hidden">
                      <div className={`h-full ${col.bg}`} style={{ width: `${value}%` }}></div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Commit Quality Gauge */}
          <div className="md:col-span-6 glass-panel p-md rounded-xl flex flex-col justify-between">
            <h3 className="font-headline-md text-headline-md mb-xs">Commit Health</h3>
            <p className="font-body-sm text-on-surface-variant mb-lg">Semantic clarity and description depth index.</p>
            <div className="flex items-center justify-center flex-grow py-md">
              <div className="relative w-48 h-24 overflow-hidden">
                <div className="absolute top-0 left-0 w-48 h-48 rounded-full border-[12px] border-surface-container"></div>
                <div
                  className="absolute top-0 left-0 w-48 h-48 rounded-full border-[12px] border-primary border-b-transparent border-l-transparent transition-transform duration-1000 ease-out"
                  style={{ transform: `rotate(${gaugeAnimated ? -45 + (180 * (lqualityPct / 100)) : -45}deg)` }}
                ></div>
                <div className="absolute bottom-0 left-1/2 -translate-x-1/2 flex flex-col items-center">
                  <span className="font-display-lg text-display-lg leading-none">{lqualityPct}</span>
                  <span className="font-label-caps text-primary">
                    {lqualityPct >= 85 ? "Elite" : lqualityPct >= 70 ? "Strong" : lqualityPct >= 50 ? "Good" : "Weak"}
                  </span>
                </div>
              </div>
            </div>
            <div className="flex gap-md justify-center border-t border-outline-variant/10 pt-md mt-md">
              <div className="text-center">
                <span className="font-headline-md block">{lqualityPct}%</span>
                <span className="font-label-caps text-on-surface-variant">Semantic</span>
              </div>
              <div className="text-center">
                <span className="font-headline-md block">
                  {data.review_participation !== undefined ? `${Math.round(data.review_participation * 100)}%` : "N/A"}
                </span>
                <span className="font-label-caps text-on-surface-variant">Participation</span>
              </div>
            </div>
          </div>

          {/* AI Developer Summary */}
          {data.llm_summary && (
            <div className="md:col-span-12 glass-panel p-md rounded-xl space-y-3 mt-4">
              <h3 className="font-label-caps text-primary font-bold uppercase tracking-wider flex items-center gap-1.5 select-none border-b border-outline-variant/20 pb-2">
                <span className="material-symbols-outlined text-sm text-primary">auto_awesome</span>
                AI Developer Summary
              </h3>
              <p className="text-body-sm text-on-surface-variant font-code-sm leading-relaxed bg-[#0a0a0a] border border-[#222222] p-4 rounded-md">
                {data.llm_summary}
              </p>
            </div>
          )}

        </div>
      </main>

      {/* Footer */}
      <footer className="w-full px-margin-desktop flex flex-col md:flex-row justify-between items-center gap-md py-xl border-t border-outline-variant/10 bg-surface">
        <div className="flex flex-col items-center md:items-start gap-xs">
          <span className="font-display-lg text-display-lg font-bold text-primary">RepoLens</span>
          <span className="font-body-sm text-body-sm text-on-surface-variant">© 2024 RepoLens. All systems operational.</span>
        </div>
        <div className="flex gap-lg">
          <a className="font-body-sm text-body-sm text-on-surface-variant hover:text-primary transition-colors" href="#">GitHub</a>
          <a className="font-body-sm text-body-sm text-on-surface-variant hover:text-primary transition-colors" href="#">Twitter</a>
          <a className="font-body-sm text-body-sm text-on-surface-variant hover:text-primary transition-colors" href="#">Documentation</a>
          <a className="font-body-sm text-body-sm text-on-surface-variant hover:text-primary transition-colors" href="#">Status</a>
        </div>
      </footer>
    </div>
  );
}