import { useEffect, useState, useCallback, useMemo, useContext } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { getJSON, isNotFound, postJSON } from "../lib/api";
import SyncBadge from "../components/SyncBadge";
import { ThemeContext } from "../lib/theme";
import { getHeatmapColorStyle } from "../lib/settings";
import Card from "../components/Card";


function formatNumber(num) {
  if (num === undefined || num === null) return "0";
  if (num >= 1000) return (num / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  return num.toString();
}

/** A developer profile must be a direct GitHub user URL, not a repository
 *  link or loose username. This keeps the profile workflow unambiguous. */
function parseGitHubProfileUrl(input) {
  try {
    const url = new URL((input || "").trim());
    const isGitHub = url.protocol === "https:"
      && (url.hostname === "github.com" || url.hostname === "www.github.com");
    const segments = url.pathname.split("/").filter(Boolean);
    const username = segments.length === 1 ? segments[0] : "";
    return isGitHub && /^[A-Za-z0-9-]+$/.test(username) ? username : "";
  } catch {
    return "";
  }
}

export default function DeveloperProfile() {
  const { settings } = useContext(ThemeContext);
  const navigate = useNavigate();
  const location = useLocation();
  const searchParams = new URLSearchParams(location.search);
  const user = searchParams.get("user");

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  // "no profile yet" (404) is an actionable state, not a failure — tracked
  // from the HTTP status, which the `detail` message never carries
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);
  const [triggeringBuild, setTriggeringBuild] = useState(false);
  const [tokenError, setTokenError] = useState(false);
  const [gaugeAnimated, setGaugeAnimated] = useState(false);
  const [selectedYear, setSelectedYear] = useState(() => new Date().getFullYear());
  // username search — the page is reachable directly from the navbar, so it
  // needs its own way in rather than only via ?user= from somewhere else
  const [inputVal, setInputVal] = useState("");
  const [inputError, setInputError] = useState(null);
  const [knownProfiles, setKnownProfiles] = useState([]);

  const openProfile = (raw) => {
    const username = parseGitHubProfileUrl(raw);
    if (!username) {
      setInputError("Enter a GitHub profile URL, e.g. https://github.com/atharva557");
      return;
    }
    setInputError(null);
    setInputVal("");
    navigate(`/profile?user=${encodeURIComponent(username)}`);
  };

  const resolvedTheme = settings.theme === "system"
    ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : settings.theme;
  const isLight = resolvedTheme === "light";
  const borderClass = isLight ? "border-[rgba(27,31,35,0.06)]" : "border-outline-variant/10";

  const getHeatmapStyle = (count) => {
    const c = getHeatmapColorStyle(count, settings.accentColor, resolvedTheme);
    // reference-design bloom: busy days glow
    return count > 5 ? { backgroundColor: c, boxShadow: isLight ? "none" : `0 0 6px ${c}` } : { backgroundColor: c };
  };

  const loadProfile = useCallback(() => {
    setLoading(true);
    setError(null);
    setNotFound(false);
    setTokenError(false);
    getJSON(`/profiles/${user}`)
      .then((profileData) => {
        setData(profileData);
        setLoading(false);
        setTimeout(() => setGaugeAnimated(true), 100);
      })
      .catch(async (e) => {
        if (isNotFound(e)) {   // never built — the normal first visit
          setNotFound(true);   // keeps the "build this profile" card available
          setTriggeringBuild(true);
          try {
            const res = await postJSON(`/profiles/${user}`);
            navigate(`/loading?job=${res.job_id}&user=${user}&next=/profile`);
          } catch (postErr) {
            if (postErr.status === 400) {  // "GITHUB_TOKEN is not configured"
              setTokenError(true);
            }
            setError(postErr.message);
            setTriggeringBuild(false);
            setLoading(false);
          }
        } else {
          setError(e.message);
          setLoading(false);
        }
      });
  }, [user, navigate]);

  useEffect(() => {
    if (user) {
      loadProfile();
    } else {
      setLoading(false);
      // already-built profiles, so the empty state offers something to click
      // instead of demanding you remember a username
      getJSON("/profiles")
        .then((res) => setKnownProfiles(res.profiles || []))
        .catch(() => setKnownProfiles([]));
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
      if (e.status === 400) {   // "GITHUB_TOKEN is not configured"
        setTokenError(true);
      } else {
        alert(`Failed to trigger profile: ${e.message}`);
      }
      setTriggeringBuild(false);
    }
  };


  const availableYears = useMemo(() => {
    const heatmapData = data?.heatmap || [];
    const yearsSet = new Set();
    heatmapData.forEach(h => {
      if (h.date) {
        const yr = parseInt(h.date.split("-")[0], 10);
        if (!isNaN(yr)) yearsSet.add(yr);
      }
    });
    if (yearsSet.size === 0) {
      yearsSet.add(new Date().getFullYear());
    }
    return Array.from(yearsSet).sort((a, b) => b - a);
  }, [data]);

  const heatmapCells = useMemo(() => {
    if (!data?.heatmap) return null;

    const hasContributions = data.heatmap.some(h => {
      if (!h.date) return false;
      const yr = parseInt(h.date.split("-")[0], 10);
      return yr === selectedYear && h.count > 0;
    });

    if (!hasContributions) return null;

    const cells = [];
    const heatmapLookup = {};
    data.heatmap.forEach((h) => {
      heatmapLookup[h.date] = h.count;
    });

    const jan1 = new Date(Date.UTC(selectedYear, 0, 1));
    const startPadding = jan1.getUTCDay();

    for (let i = 0; i < startPadding; i++) {
      cells.push({ isPadding: true, row: i, column: 0 });
    }

    let current = new Date(Date.UTC(selectedYear, 0, 1));
    while (current.getUTCFullYear() === selectedYear) {
      const dateStr = current.toISOString().split("T")[0];
      const count = heatmapLookup[dateStr] || 0;
      const dayOfWeek = current.getUTCDay();
      const cellIndex = cells.length;
      const col = Math.floor(cellIndex / 7);

      const formattedDate = current.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });
      const contributionsText = count > 0 ? `${count} Contribution${count === 1 ? "" : "s"}` : "No Contributions";

      cells.push({
        date: dateStr,
        count,
        dayOfWeek,
        row: dayOfWeek,
        column: col,
        isPadding: false,
        title: `${formattedDate}\n${contributionsText}`
      });
      current.setUTCDate(current.getUTCDate() + 1);
    }

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
  }, [data, selectedYear]);

  const totalColumns = heatmapCells ? Math.ceil(heatmapCells.length / 7) : 0;

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

  const monthLabels = useMemo(() => getMonthLabels(heatmapCells || []), [heatmapCells]);

  // No ?user= — the search screen. This guard comes FIRST: `loading` starts
  // true, so checking it earlier would flash a spinner, and the main render
  // below dereferences `data.user` on a null `data` and would throw outright.
  if (!user) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface p-6 relative overflow-hidden">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-primary/5 rounded-full blur-[100px] pointer-events-none"></div>
        <div className="relative w-full max-w-[560px] p-10 rounded-3xl bg-surface-container-lowest/60 backdrop-blur-xl border border-outline-variant/40 shadow-2xl shadow-primary/10 flex flex-col items-center gap-6">
          <div className="w-20 h-20 rounded-full bg-primary/10 flex items-center justify-center border border-primary/20 shadow-inner">
            <span className="material-symbols-outlined text-primary text-[40px]">person_search</span>
          </div>
          <div className="space-y-3 text-center">
            <h2 className="font-display-lg text-3xl text-on-surface font-bold tracking-tight">
              Developer Profile
            </h2>
            <p className="text-sm text-on-surface-variant leading-relaxed font-body">
              Paste a GitHub user profile URL to analyze contribution patterns,
              languages, review participation and message quality.
            </p>
          </div>

          <form
            onSubmit={(e) => { e.preventDefault(); openProfile(inputVal); }}
            className="w-full relative mt-4"
          >
            <div className="flex items-stretch w-full rounded-md overflow-hidden border border-primary/50 bg-primary/5 focus-within:ring-2 focus-within:ring-primary/20">
              <div className="pl-4 pr-2 pt-4 flex items-start text-primary/60">
                <span className="material-symbols-outlined text-[20px]">search</span>
              </div>
              <textarea
                autoFocus
                rows={2}
                value={inputVal}
                onChange={(e) => { setInputVal(e.target.value); setInputError(null); }}
                className="flex-grow min-w-0 resize-none bg-transparent border-none py-3 px-2 focus:outline-none font-code text-[14px] text-on-surface placeholder:text-on-surface-variant/40"
                placeholder="https://github.com/atharva557"
                aria-label="GitHub profile URL"
                aria-describedby="github-profile-url-help"
              />
              <button
                type="submit"
                disabled={!inputVal.trim()}
                className="px-6 bg-primary text-on-primary font-bold text-[14px] transition-all disabled:opacity-50 hover:bg-primary-container shrink-0"
              >
                Profile
              </button>
            </div>
            <p id="github-profile-url-help" className="mt-2 text-center text-[11px] font-code text-on-surface-variant">
              Accepts direct profile URLs only — not usernames or repository links.
            </p>
            {inputError && (
              <div className="absolute top-full mt-2 w-full text-center text-error text-[12px] font-code">
                {inputError}
              </div>
            )}
          </form>

          {knownProfiles.length > 0 && (
            <div className="w-full pt-4 border-t border-outline-variant/40 space-y-2">
              <p className="text-label text-on-surface-variant uppercase tracking-widest">
                Already profiled
              </p>
              <div className="flex flex-wrap gap-2">
                {knownProfiles.slice(0, 12).map((p) => (
                  <button
                    key={p.username}
                    type="button"
                    onClick={() => navigate(`/profile?user=${encodeURIComponent(p.username)}`)}
                    title={p.primary_type || "profiled"}
                    className="px-3 py-1.5 rounded-full border border-outline-variant hover:border-primary hover:text-primary text-label font-code transition-colors"
                  >
                    @{p.username}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Navigation from the URL form reuses this component instance. On the
  // render immediately after `?user=` changes, the effect that starts the
  // request has not run yet, so `loading` can still be false and `data` null.
  // Keep rendering a loading state until the requested profile is available.
  const waitingForProfile = loading || !data || data.username !== user;

  if (waitingForProfile && !notFound && !error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-primary border-t-transparent rounded-full motion-safe:animate-spin mx-auto"></div>
          <p className="font-code-sm text-on-surface-variant uppercase tracking-widest animate-pulse">
            Retrieving developer profile...
          </p>
        </div>
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <Card className="p-8 text-center space-y-6 max-w-[28rem] w-full">
          <span className="material-symbols-outlined text-primary text-[64px]">person_off</span>
          <div className="space-y-2">
            <h2 className="text-[var(--font-size-heading)] text-primary font-bold">Profile Not Found</h2>
            <p className="text-[var(--font-size-body)] text-on-surface-variant leading-relaxed">
              No developer profile index found for <span className="text-on-surface font-bold">@{user}</span>.
            </p>
          </div>
          {tokenError && (
            <div className="p-sm bg-error-container/20 border border-error-container/50 text-error rounded-lg text-left text-[var(--font-size-body)]">
              <p className="font-bold flex items-center gap-1 mb-1"><span className="material-symbols-outlined text-sm">warning</span> ACCESS DENIED</p>
              <p>The server lacks a GitHub API Token. Rebuilding profiles requires GITHUB_TOKEN.</p>
            </div>
          )}
          <div className="space-y-3 pt-2">
            <button
              onClick={handleBuildProfile}
              disabled={triggeringBuild}
              aria-live="polite"
              className="w-full bg-primary text-on-primary font-label-caps py-sm rounded-lg hover:shadow-[0_0_15px_rgba(99,102,241,0.5)] transition-all disabled:opacity-50 active:scale-95"
            >
              {triggeringBuild ? "BUILDING PIPELINE..." : `BUILD @${user} PROFILE`}
            </button>
            <button
              onClick={() => navigate("/")}
              className="w-full border border-outline-variant hover:bg-surface-container-low text-on-surface-variant font-label-caps py-sm rounded-lg transition-colors active:scale-95"
            >
              RETURN HOME
            </button>
          </div>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <Card className="p-8 text-center space-y-4 max-w-[28rem] w-full">
          <span className="material-symbols-outlined text-error text-[54px]">warning</span>
          <h2 className="text-[var(--font-size-heading)] text-error font-bold">Error loading profile</h2>
          <p className="text-[var(--font-size-body)] text-on-surface-variant leading-relaxed break-words">{error}</p>
          <button
            onClick={loadProfile}
            className="w-full bg-primary text-on-primary font-label-caps py-sm rounded-lg active:scale-95 transition-all cursor-pointer"
          >
            RETRY
          </button>
        </Card>
      </div>
    );
  }

  const social = data.user || {};
  const hasSocial = Object.keys(social).length > 0;
  const lquality = data.commit_message_quality || 0;
  const lqualityPct = Math.round(lquality * 10);


  // categorical palette for languages / activity types — fixed hues that read
  // clearly in both themes (a single accent can't separate 6 series)
  const CATEGORICAL = ["#f5a524", "#3fb950", "#0ea5e9", "#c084fc", "#f472b6", "#94a3b8"];
  const langs = (data.languages || []).slice(0, 6);
  const activityEntries = Object.entries(data.activity_split || {})
    .sort((a, b) => b[1] - a[1]);
  const qualityLabel =
    lqualityPct >= 85 ? "Elite" : lqualityPct >= 70 ? "Strong"
      : lqualityPct >= 50 ? "Good" : "Weak";
  const participationDisplay =
    typeof data.review_ratio === "number" ? `${Math.round(data.review_ratio * 100)}%`
      : typeof data.review_participation === "string" ? data.review_participation.split(" ")[0]
        : "N/A";

  return (
    <div className="min-h-screen overflow-x-hidden">


      <main className="mt-sm pt-sm pb-xl px-margin-mobile md:px-margin-desktop max-w-[1440px] mx-auto">
        {/* Profile Header */}
        <Card className="p-md mb-lg flex flex-col md:flex-row gap-lg items-center md:items-start relative overflow-hidden">
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
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-sm mb-xs">
              <h1 className="font-display-lg text-display-lg leading-none">
                @{user} <span className="text-on-surface-variant/50 mx-2">•</span> <span className="text-primary glow-text">{data.primary_type || "Contributor"}</span>
              </h1>

            </div>
            {inputError && (
              <p className="text-error text-[12px] font-code mb-xs">{inputError}</p>
            )}
            <p className="font-body-lg text-on-surface-variant mb-md max-w-2xl">
              {data.label || social.bio || ""}
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


        </Card>

        {/* Bento Grid Section */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-gutter">
          {/* Quick Stats */}
          <div className="md:col-span-12 grid grid-cols-2 lg:grid-cols-4 gap-gutter">
            <Card className="p-md flex flex-col justify-between">
              <span className="font-label-caps text-on-surface-variant mb-sm">Analyzed Commits</span>
              <div className="flex items-end justify-between">
                <span className="font-display-lg text-display-lg text-primary leading-none">{formatNumber(data.commits_analyzed)}</span>
                <span className="text-tertiary text-[var(--font-size-label)] flex items-center"><span className="material-symbols-outlined text-sm">trending_up</span> Profiler</span>
              </div>
            </Card>
            <Card className="p-md flex flex-col justify-between">
              <span className="font-label-caps text-on-surface-variant mb-sm">PRs Merged</span>
              <div className="flex items-end justify-between">
                <span className="font-display-lg text-display-lg text-secondary leading-none">{formatNumber(data.prs_merged)}</span>
                <span className="text-tertiary text-[var(--font-size-label)] flex items-center"><span className="material-symbols-outlined text-sm">trending_up</span> out of {data.authored_prs || 0}</span>
              </div>
            </Card>
            <Card className="p-md flex flex-col justify-between">
              <span className="font-label-caps text-on-surface-variant mb-sm">Issues Resolved</span>
              <div className="flex items-end justify-between">
                <span className="font-display-lg text-display-lg text-tertiary leading-none">{formatNumber(data.issues_resolved)}</span>
                <span className="text-on-surface-variant text-[var(--font-size-label)]">Verified</span>
              </div>
            </Card>
            <Card className="p-md flex flex-col justify-between">
              <span className="font-label-caps text-on-surface-variant mb-sm">Years Active</span>
              <div className="flex items-end justify-between">
                <span className="font-display-lg text-display-lg text-on-surface leading-none">{social.years_active?.toFixed(1) || "1.0"}</span>
                <span className="text-on-surface-variant text-[var(--font-size-label)]">Experience</span>
              </div>
            </Card>
          </div>

          {/* Heatmap */}
          <Card className="md:col-span-8 flex flex-col">
            <div className="terminal-header px-md py-sm flex items-center justify-between">
              <div className="flex gap-2">
                <div className="dot"></div><div className="dot"></div><div className="dot"></div>
              </div>
              <span className="font-code-sm text-on-surface-variant">contribution matrix</span>
            </div>
            <div className="p-md">
              <div className="flex justify-between items-center mb-6 min-w-full">
                <div className="flex items-center gap-4">
                  <h3 className="text-[11px] text-on-surface-variant font-code font-bold uppercase tracking-widest">
                    Annual Contribution
                  </h3>
                  {availableYears.length > 0 && (
                    <select
                      value={selectedYear}
                      onChange={(e) => setSelectedYear(parseInt(e.target.value, 10))}
                      className="bg-surface-container border border-outline-variant text-on-surface text-[10px] font-code rounded px-2 py-0.5 outline-none cursor-pointer hover:border-outline focus:ring-1 focus:ring-primary"
                    >
                      {availableYears.map((yr) => (
                        <option key={yr} value={yr}>
                          {yr}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                <div className="flex items-center gap-3 font-code text-[11px] text-on-surface-variant">
                  <span>Less</span>
                  <div className="flex gap-1">
                    {[0, 2, 5, 8, 12].map((val) => (
                      <div
                        key={val}
                        className={`w-[13px] h-[13px] rounded-[3px] ${val === 0 ? "border border-outline-variant/30" : ""}`}
                        style={getHeatmapStyle(val)}
                      />
                    ))}
                  </div>
                  <span>More</span>
                </div>
              </div>

              {heatmapCells ? (
                <>
                  {/* Scrollable Area */}
                  <div className="w-full overflow-x-auto pb-4 scrollbar-thin scrollbar-thumb-outline-variant/30 scrollbar-track-transparent">
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
                  </div>
                </>
              ) : (
                <div className="flex flex-col items-center justify-center py-12 text-center border border-dashed border-outline-variant/30 rounded-xl bg-surface/30">
                  <span className="material-symbols-outlined text-outline-variant text-4xl mb-3">calendar_month</span>
                  <p className="font-body-lg text-on-surface-variant mb-1">
                    No contribution data available for this year.
                  </p>
                  <p className="font-body-sm text-outline-variant">
                    Try selecting another year.
                  </p>
                </div>
              )}
            </div>
          </Card>

          {/* Top Languages — GitHub-style segmented bar + legend */}
          <Card className="md:col-span-4 p-5 flex flex-col">
            <h3 className="text-[11px] font-code font-bold text-on-surface-variant uppercase tracking-widest mb-4 flex items-center gap-1.5">
              <span className="material-symbols-outlined text-sm text-primary">code</span>Top Languages
            </h3>
            {langs.length > 0 ? (
              <div className="flex flex-col flex-grow">
                <div className="flex w-full h-2.5 rounded-full overflow-hidden mb-5 bg-surface-container-highest">
                  {langs.map((lang, idx) => (
                    <div
                      key={lang.name}
                      style={{ width: `${lang.pct}%`, backgroundColor: CATEGORICAL[idx % CATEGORICAL.length] }}
                      title={`${lang.name} ${lang.pct.toFixed(1)}%`}
                    />
                  ))}
                </div>
                <div className="space-y-2.5">
                  {langs.map((lang, idx) => (
                    <div key={lang.name} className="flex items-center gap-2.5">
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: CATEGORICAL[idx % CATEGORICAL.length] }} />
                      <span className="font-body-sm text-on-surface truncate flex-grow">{lang.name}</span>
                      <span className="font-code text-xs text-on-surface-variant tabular-nums">{lang.pct.toFixed(1)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-on-surface-variant font-body-sm py-8 text-center flex-grow flex items-center justify-center">No language data</div>
            )}
          </Card>

          {/* Contribution Mix — ranked developer-type distribution */}
          <Card className="md:col-span-9 p-5">
            <h3 className="text-[11px] font-code font-bold text-on-surface-variant uppercase tracking-widest mb-4 flex items-center gap-1.5">
              <span className="material-symbols-outlined text-sm text-primary">donut_small</span>Contribution Mix
            </h3>
            <div className="space-y-3.5">
              {activityEntries.map(([key, value], idx) => {
                const isTop = idx === 0 && value > 0;
                return (
                  <div key={key}>
                    <div className="flex justify-between items-baseline mb-1.5">
                      <span className={`font-body-sm ${isTop ? "text-on-surface font-semibold" : "text-on-surface-variant"}`}>{key}</span>
                      <span className="font-code text-xs tabular-nums text-on-surface-variant">{Math.round(value)}%</span>
                    </div>
                    <div className="w-full h-2 bg-surface-container-highest rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-700"
                        style={{ width: `${value}%`, backgroundColor: isTop ? "var(--color-primary)" : CATEGORICAL[idx % CATEGORICAL.length] }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>

          {/* Commit Health — clean conic ring + sub-stats */}
          <Card className="md:col-span-3 p-5 flex flex-col">
            <h3 className="text-[11px] font-code font-bold text-on-surface-variant uppercase tracking-widest mb-4 flex items-center gap-1.5">
              <span className="material-symbols-outlined text-sm text-primary">verified_user</span>Commit Health
            </h3>
            <div className="flex flex-col items-center justify-center flex-grow gap-4">
              <div
                className="relative w-32 h-32 rounded-full flex items-center justify-center"
                style={{ background: `conic-gradient(var(--color-primary) ${gaugeAnimated ? lqualityPct : 0}%, var(--color-surface-container-highest) 0)`, transition: "background 1s ease-out" }}
              >
                <div className="w-[104px] h-[104px] rounded-full bg-surface-container flex flex-col items-center justify-center">
                  <span className="font-stat text-3xl font-bold leading-none text-on-surface">{lqualityPct}</span>
                  <span className="font-label-caps text-primary text-[10px] mt-0.5">{qualityLabel}</span>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2 w-full border-t border-outline-variant/20 pt-4">
                <div className="text-center">
                  <span className="font-headline-md text-lg block text-on-surface tabular-nums">{lqualityPct}%</span>
                  <span className="font-label-caps text-on-surface-variant text-[10px]">Semantic</span>
                </div>
                <div className="text-center">
                  <span className="font-headline-md text-lg block text-on-surface tabular-nums">{participationDisplay}</span>
                  <span className="font-label-caps text-on-surface-variant text-[10px]">Reviews</span>
                </div>
              </div>
            </div>
          </Card>

          {/* AI Developer Summary — always visible: hiding it silently made
              "why is there no summary?" a support question. Profiles built
              while no LLM was reachable have llm_summary=null; a re-sync
              regenerates it. */}
          <Card className="md:col-span-12 p-md space-y-3 mt-4 border-l-4 border-l-primary">
            <h3 className="text-[11px] font-code font-bold text-primary uppercase tracking-widest flex items-center gap-1.5 select-none border-b border-outline-variant/20 pb-2">
              <span className="material-symbols-outlined text-sm text-primary">auto_awesome</span>
              AI Developer Summary
            </h3>
            {data.llm_summary ? (
              <p className="text-[var(--font-size-body)] text-on-surface leading-relaxed bg-background border border-outline-variant/40 p-4 rounded-md">
                {data.llm_summary}
              </p>
            ) : (
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-background border border-outline-variant/40 p-4 rounded-md">
                <p className="text-[var(--font-size-body)] text-on-surface-variant">
                  No AI summary on this profile — it was built while no LLM was
                  reachable. Re-sync the profile to generate one.
                </p>
                <button
                  onClick={handleBuildProfile}
                  disabled={triggeringBuild}
                  className="shrink-0 h-9 px-4 bg-primary text-on-primary font-code text-[12px] font-bold rounded-lg hover:opacity-90 transition-all active:scale-95 disabled:opacity-50 glow-primary"
                >
                  {triggeringBuild ? "REBUILDING…" : "RE-SYNC PROFILE"}
                </button>
              </div>
            )}
          </Card>

        </div>
      </main>

    </div>
  );
}
