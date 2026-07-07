import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { getJSON, postJSON } from "../lib/api";
import { PieChart, Pie, Cell, ResponsiveContainer } from "recharts";

const DEFAULT_USER = "gaearon";
const COLORS = ["#6366f1", "#a855f7", "#ffb783", "#908fa0", "#ffb4ab", "#c0c1ff"];

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

export default function DeveloperProfile() {
  const navigate = useNavigate();
  const user = new URLSearchParams(window.location.search).get("user") || DEFAULT_USER;

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [searchVal, setSearchVal] = useState("");
  const [triggeringBuild, setTriggeringBuild] = useState(false);
  const [tokenError, setTokenError] = useState(false);

  const loadProfile = useCallback(() => {
    setLoading(true);
    setError(null);
    setTokenError(false);
    getJSON(`/profiles/${user}`)
      .then((profileData) => {
        setData(profileData);
        setLoading(false);
      })
      .catch(async (e) => {
        const msg = String(e);
        if (msg.includes("404") || msg.includes("no profile") || msg.includes("POST /profiles")) {
          console.log(`Profile for @${user} not found. Auto-triggering build...`);
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
    loadProfile();
  }, [loadProfile]);

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

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    let val = searchVal.trim();
    if (val) {
      // Extract username from GitHub profile URL
      const match = val.match(/github\.com\/([a-zA-Z0-9_-]+)/i);
      if (match) {
        val = match[1];
      } else {
        // Strip protocols and leading path variables if any
        val = val.replace(/^(https?:\/\/)?(www\.)?github\.com\//i, "");
        val = val.split("/")[0];
      }
      navigate(`/profile?user=${val}`);
      setSearchVal("");
    }
  };

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-[#000000] text-on-surface">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-indigo-primary border-t-transparent rounded-full animate-spin mx-auto"></div>
          <p className="font-code text-label text-indigo-on-surface-variant uppercase tracking-widest animate-pulse">
            Retrieving developer profile...
          </p>
        </div>
      </div>
    );
  }

  // Handle 404 / Profile Not Found State
  if (error && (error.includes("404") || error.includes("not found"))) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-[#000000] text-on-surface p-6">
        <div className="max-w-md w-full bg-[#111111] border border-indigo-outline-variant/30 p-8 text-center space-y-6 rounded-lg">
          <span className="material-symbols-outlined text-indigo-primary text-[64px]">person_off</span>
          
          <div className="space-y-2">
            <h2 className="font-code text-heading-lg text-indigo-primary font-bold">Profile Not Found</h2>
            <p className="text-xs text-indigo-on-surface-variant leading-relaxed">
              No developer profile index found for <span className="text-on-surface font-bold">@{user}</span>.
            </p>
          </div>

          {tokenError && (
            <div className="p-3.5 bg-error-container/20 border border-error-container/50 text-error rounded-sm font-code text-left text-[11px] leading-relaxed space-y-1">
              <p className="font-bold flex items-center gap-1"><span className="material-symbols-outlined text-xs">warning</span> ACCESS DENIED (400)</p>
              <p>The server lacks a GitHub API Token. Rebuilding profiles requires configuring a GITHUB_TOKEN in the server environment variables.</p>
            </div>
          )}

          <div className="space-y-3 pt-2">
            <button
              onClick={handleBuildProfile}
              disabled={triggeringBuild}
              className="w-full bg-indigo-primary hover:opacity-90 text-on-primary font-code font-bold py-3 rounded-md transition-all disabled:opacity-50 active:scale-[0.98]"
            >
              {triggeringBuild ? "BUILDING PIPELINE..." : `BUILD @${user} PROFILE`}
            </button>
            <button
              onClick={() => navigate("/")}
              className="w-full border border-indigo-outline-variant/40 hover:bg-surface-container text-indigo-on-surface-variant font-code font-bold py-2.5 rounded-md text-xs transition-colors"
            >
              RETURN_HOME
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Handle general error
  if (error) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-[#000000] text-on-surface p-6">
        <div className="max-w-md w-full bg-[#111111] border border-error/30 p-8 text-center space-y-4 rounded-lg">
          <span className="material-symbols-outlined text-error text-[54px]">warning</span>
          <h2 className="font-code text-heading-lg text-error font-bold">Error loading developer profile</h2>
          <p className="text-xs text-indigo-on-surface-variant leading-relaxed break-words">{error}</p>
          <button
            onClick={loadProfile}
            className="w-full bg-indigo-primary hover:opacity-90 text-on-primary font-code font-bold py-2 rounded-md"
          >
            RETRY
          </button>
        </div>
      </div>
    );
  }

  // Generate 365 Days Grid for Heatmap
  const generateHeatmapGrid = () => {
    const today = new Date();
    const cells = [];
    const heatmapLookup = {};
    
    if (data.heatmap) {
      data.heatmap.forEach((h) => {
        heatmapLookup[h.date] = h.count;
      });
    }

    const startDate = new Date();
    startDate.setDate(today.getDate() - 364);

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
    if (count === 0) return "bg-[#111111]";
    if (count <= 2) return "bg-indigo-primary/20";
    if (count <= 5) return "bg-indigo-primary/40";
    if (count <= 9) return "bg-indigo-primary/70";
    return "bg-indigo-primary";
  };

  // Safe variables fallback
  const social = data.user || {};
  const hasSocial = Object.keys(social).length > 0;
  const lquality = data.commit_message_quality || 0; // 0..10
  
  // Custom Gauge setup properties
  // Math circumference of radius 40 arc is 2 * pi * 40 = 251.3
  // Semi-circle length is ~125.6
  const strokeDash = 125.6;
  const strokeOffset = strokeDash - (strokeDash * lquality) / 10;

  return (
    <div className="min-h-screen bg-[#000000] text-on-surface pb-12 font-body selection:bg-indigo-primary selection:text-on-primary">
      <main className="pt-8 px-margin-mobile md:px-margin-desktop max-w-[1440px] mx-auto space-y-6">
        
        {/* Search profile input bar */}
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 border-b border-indigo-outline-variant/20 pb-4">
          <h2 className="font-headline-lg text-2xl font-bold bg-gradient-to-r from-indigo-primary to-indigo-secondary bg-clip-text text-transparent">
            Developer Profile
          </h2>
          <form onSubmit={handleSearchSubmit} className="relative flex items-center w-full sm:w-80">
            <span className="material-symbols-outlined absolute left-3 text-indigo-on-surface-variant/50 text-[14px]">search</span>
            <input
              type="text"
              placeholder="Search GitHub username..."
              value={searchVal}
              onChange={(e) => setSearchVal(e.target.value)}
              className="w-full bg-[#111111] border border-indigo-outline-variant/30 rounded pl-9 pr-24 py-1.5 font-code text-xs focus:outline-none focus:border-indigo-primary text-on-surface"
            />
            <button
              type="submit"
              className="absolute right-1 text-[9px] bg-indigo-primary text-on-primary font-code font-bold px-2 py-1 hover:opacity-90 rounded-sm"
            >
              QUERY
            </button>
          </form>
        </div>

        {/* Profile Header Box */}
        <section className="bg-[#111111] border border-indigo-outline-variant/30 p-6 rounded-xl flex flex-col md:flex-row gap-6 items-center md:items-start relative overflow-hidden">
          <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-indigo-primary via-indigo-secondary to-indigo-tertiary"></div>
          
          <div className="relative shrink-0">
            <div className="w-28 h-28 rounded-xl overflow-hidden border border-indigo-primary/20 shadow-xl bg-surface-container-highest">
              {hasSocial && social.avatar_url ? (
                <img className="w-full h-full object-cover" src={social.avatar_url} alt={data.username} />
              ) : (
                <div className="w-full h-full flex items-center justify-center bg-indigo-primary/10 text-indigo-primary font-bold text-3xl font-code">
                  {data.username.slice(0, 2).toUpperCase()}
                </div>
              )}
            </div>
            <div className="absolute -bottom-2 -right-2 bg-black border border-indigo-outline-variant/40 p-0.5 rounded-lg flex items-center justify-center select-none">
              <span className="material-symbols-outlined text-indigo-primary text-xs font-bold">verified</span>
            </div>
          </div>

          <div className="flex-grow text-center md:text-left space-y-4">
            <div className="space-y-1.5">
              <div className="flex flex-col md:flex-row md:items-end gap-2 justify-center md:justify-start">
                <h1 className="font-display-lg text-3xl font-bold leading-none">{social.name || data.username}</h1>
                <span className="px-2.5 py-0.5 rounded-full bg-indigo-secondary/15 border border-indigo-secondary/30 text-indigo-secondary font-code text-[9px] uppercase tracking-wider font-bold inline-block mx-auto md:mx-0">
                  {data.primary_type || "Feature Builder"}
                </span>
              </div>
              <p className="font-code text-[11px] text-indigo-on-surface-variant">@{data.username}</p>
            </div>
            
            <p className="text-xs text-indigo-on-surface-variant max-w-2xl leading-relaxed">
              {social.bio || `${social.name || data.username} is a verified contributor profiled on RepoLens.`}
            </p>
            
            <div className="flex flex-wrap justify-center md:justify-start gap-6 font-code text-xs">
              <div className="flex flex-col">
                <span className="font-bold text-indigo-primary text-sm">{formatNumber(social.followers) || "0"}</span>
                <span className="text-[9px] uppercase text-indigo-on-surface-variant/60">Followers</span>
              </div>
              <div className="flex flex-col">
                <span className="font-bold text-indigo-primary text-sm">{formatNumber(social.following) || "0"}</span>
                <span className="text-[9px] uppercase text-indigo-on-surface-variant/60">Following</span>
              </div>
              <div className="flex flex-col">
                <span className="font-bold text-indigo-primary text-sm">{formatNumber(social.public_repos) || "0"}</span>
                <span className="text-[9px] uppercase text-indigo-on-surface-variant/60">Repositories</span>
              </div>
            </div>
          </div>
          
          <div className="flex gap-2">
            <button
              onClick={handleBuildProfile}
              disabled={triggeringBuild}
              className="bg-indigo-primary hover:opacity-95 text-on-primary font-code text-xs font-bold px-4 py-2 rounded-md active:scale-95 disabled:opacity-50"
            >
              {triggeringBuild ? "PIPELINE..." : "REFRESH_INDEX"}
            </button>
          </div>
        </section>

        {/* Bento Grid */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
          {/* Quick Stats Grid */}
          <div className="md:col-span-12 grid grid-cols-2 lg:grid-cols-4 gap-6">
            <div className="bg-[#111111] border border-indigo-outline-variant/30 p-4 rounded-xl flex flex-col justify-between group hover:border-[#333333] transition-all">
              <span className="font-code text-[10px] text-indigo-on-surface-variant/60 uppercase font-bold select-none" title="Commits indexed inside workspace profiles">Analyzed Commits</span>
              <div className="flex items-end justify-between mt-3">
                <span className="font-stat text-2xl font-bold text-indigo-primary">{formatNumber(data.commits_analyzed)}</span>
                <span className="text-[8px] text-indigo-on-surface-variant/40 font-code uppercase">Profile Cap</span>
              </div>
            </div>
            <div className="bg-[#111111] border border-indigo-outline-variant/30 p-4 rounded-xl flex flex-col justify-between group hover:border-[#333333] transition-all">
              <span className="font-code text-[10px] text-indigo-on-surface-variant/60 uppercase font-bold select-none">PRs Merged</span>
              <div className="flex items-end justify-between mt-3">
                <span className="font-stat text-2xl font-bold text-indigo-secondary">{formatNumber(data.prs_merged)}</span>
                <span className="text-indigo-tertiary font-code text-[10px] flex items-center">
                  out of {data.authored_prs || data.prs_merged || 0}
                </span>
              </div>
            </div>
            <div className="bg-[#111111] border border-indigo-outline-variant/30 p-4 rounded-xl flex flex-col justify-between group hover:border-[#333333] transition-all">
              <span className="font-code text-[10px] text-indigo-on-surface-variant/60 uppercase font-bold select-none">Issues Resolved</span>
              <div className="flex items-end justify-between mt-3">
                <span className="font-stat text-2xl font-bold text-indigo-tertiary">{formatNumber(data.issues_resolved)}</span>
                <span className="text-indigo-on-surface-variant/40 font-code text-[9px]">Verified</span>
              </div>
            </div>
            <div className="bg-[#111111] border border-indigo-outline-variant/30 p-4 rounded-xl flex flex-col justify-between group hover:border-[#333333] transition-all">
              <span className="font-code text-[10px] text-indigo-on-surface-variant/60 uppercase font-bold select-none">Years Active</span>
              <div className="flex items-end justify-between mt-3">
                <span className="font-stat text-2xl font-bold text-on-surface">{social.years_active?.toFixed(1) || "1.0"}</span>
                <span className="text-indigo-on-surface-variant/40 font-code text-[9px] uppercase">Experience</span>
              </div>
            </div>
          </div>

          {/* Annual Velocity Heatmap */}
          <div className="md:col-span-8 bg-[#111111] border border-indigo-outline-variant/30 rounded-xl overflow-hidden flex flex-col">
            <div className="bg-[#050505] px-4 py-3 border-b border-[#222222] flex items-center justify-between">
              <span className="font-code text-xs text-indigo-on-surface-variant font-bold">contribution_density.sh</span>
              <span className="text-[10px] font-code text-indigo-on-surface-variant/50 uppercase">Annual Activity Calendar</span>
            </div>
            <div className="p-4 space-y-4">
              <div className="flex flex-wrap gap-0.5 overflow-x-auto pb-2 scrollbar-thin select-none">
                <div className="grid grid-flow-col grid-rows-7 gap-0.5">
                  {heatmapCells.map((cell, idx) => (
                    <div
                      key={idx}
                      title={`${cell.date}: ${cell.count} commits`}
                      className={`w-2.5 h-2.5 rounded-[1px] ${getHeatmapColor(cell.count)} hover:ring-1 hover:ring-indigo-primary`}
                    ></div>
                  ))}
                </div>
              </div>
              <div className="flex justify-between items-center text-[10px] text-indigo-on-surface-variant/60 font-code select-none">
                <span>Less Velocity</span>
                <div className="flex gap-0.5">
                  <div className="w-2.5 h-2.5 bg-[#111111] rounded-[1px]"></div>
                  <div className="w-2.5 h-2.5 bg-indigo-primary/20 rounded-[1px]"></div>
                  <div className="w-2.5 h-2.5 bg-indigo-primary/40 rounded-[1px]"></div>
                  <div className="w-2.5 h-2.5 bg-indigo-primary/70 rounded-[1px]"></div>
                  <div className="w-2.5 h-2.5 bg-indigo-primary rounded-[1px]"></div>
                </div>
                <span>More Velocity</span>
              </div>
            </div>
          </div>

          {/* Language circular chart */}
          <div className="md:col-span-4 bg-[#111111] border border-indigo-outline-variant/30 p-4 rounded-xl flex flex-col items-center justify-center text-center">
            <h3 className="font-code text-xs text-indigo-on-surface-variant/60 uppercase font-bold mb-4 select-none">Top Languages split</h3>
            
            {data.languages && data.languages.length > 0 ? (
              <div className="w-full space-y-4">
                <div className="h-28 w-full relative flex items-center justify-center">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={data.languages}
                        cx="50%"
                        cy="50%"
                        innerRadius={30}
                        outerRadius={45}
                        paddingAngle={2}
                        dataKey="pct"
                      >
                        {data.languages.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                        ))}
                      </Pie>
                    </PieChart>
                  </ResponsiveContainer>
                  
                  {/* Overlay text */}
                  <div className="absolute flex flex-col">
                    <span className="font-code text-[11px] font-bold text-indigo-primary leading-none">
                      {data.languages[0].name}
                    </span>
                    <span className="text-[9px] text-indigo-on-surface-variant/40 mt-0.5 leading-none">
                      {data.languages[0].pct.toFixed(0)}%
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 text-left font-code text-[10px]">
                  {data.languages.slice(0, 4).map((lang, idx) => (
                    <div key={lang.name} className="flex items-center gap-1.5 text-indigo-on-surface-variant">
                      <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: COLORS[idx % COLORS.length] }}></div>
                      <span className="truncate" title={`${lang.name}: ${lang.pct.toFixed(1)}%`}>
                        {lang.name} ({Math.round(lang.pct)}%)
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="py-6 text-indigo-on-surface-variant/40 text-xs font-code">
                No language data compiled.
              </div>
            )}
          </div>

          {/* Left Split column: Contribution Mix */}
          <div className="md:col-span-6 bg-[#111111] border border-indigo-outline-variant/30 p-4 rounded-xl">
            <h3 className="font-code text-xs text-indigo-on-surface-variant/60 uppercase font-bold mb-4 border-b border-indigo-outline-variant/20 pb-2 select-none">Contribution Mix</h3>
            <div className="space-y-4 pt-1 font-code text-xs">
              {Object.entries(data.activity_split || {}).map(([key, value]) => (
                <div key={key} className="space-y-1.5">
                  <div className="flex justify-between">
                    <span className="text-on-surface">{key}</span>
                    <span className="text-indigo-primary font-bold">{value}%</span>
                  </div>
                  <div className="w-full bg-[#1c1b1b] h-1.5 overflow-hidden rounded-full">
                    <div
                      className="bg-indigo-primary h-full rounded-full"
                      style={{ width: `${value}%` }}
                    ></div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right Split column: Commit Message Quality Gauge */}
          <div className="md:col-span-6 bg-[#111111] border border-indigo-outline-variant/30 p-4 rounded-xl flex flex-col justify-between">
            <div>
              <h3 className="font-code text-xs text-indigo-on-surface-variant/60 uppercase font-bold mb-1 select-none">Commit Quality Index</h3>
              <p className="text-[10px] text-indigo-on-surface-variant/40 font-code">Semantic writing and structure evaluation score.</p>
            </div>
            
            <div className="flex items-center justify-center flex-grow py-6">
              <div className="relative w-48 h-24 overflow-hidden select-none">
                {/* SVG Gauge */}
                <svg className="w-48 h-24 absolute top-0 left-0" viewBox="0 0 100 50">
                  {/* Gauge Track */}
                  <path
                    d="M 10,50 A 40,40 0 0,1 90,50"
                    fill="none"
                    stroke="#1c1b1b"
                    strokeWidth="8"
                    strokeLinecap="round"
                  />
                  {/* Gauge Value */}
                  <path
                    d="M 10,50 A 40,40 0 0,1 90,50"
                    fill="none"
                    stroke="url(#indigoGrad)"
                    strokeWidth="8"
                    strokeLinecap="round"
                    strokeDasharray={strokeDash}
                    strokeDashoffset={strokeOffset}
                    className="transition-all duration-1000 ease-out"
                  />
                  <defs>
                    <linearGradient id="indigoGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                      <stop offset="0%" stopColor="#6366f1" />
                      <stop offset="100%" stopColor="#ddb7ff" />
                    </linearGradient>
                  </defs>
                </svg>

                <div className="absolute bottom-0 left-0 right-0 flex flex-col items-center">
                  <span className="font-stat text-3xl font-bold leading-none">
                    {Math.round(lquality * 10)}
                  </span>
                  <span className="font-code text-[9px] uppercase tracking-wider text-indigo-primary font-bold mt-1">
                    {lquality >= 8.5 ? "Elite Class" : lquality >= 7.0 ? "Strong Class" : lquality >= 5.0 ? "Good" : "Needs Work"}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex gap-4 justify-center border-t border-indigo-outline-variant/20 pt-4 mt-2">
              <div className="text-center font-code">
                <span className="text-sm font-bold block text-indigo-primary">{Math.round(lquality * 10)}%</span>
                <span className="text-[8px] uppercase tracking-wider text-indigo-on-surface-variant/50">Semantic rating</span>
              </div>
              <div className="text-center font-code">
                <span className="text-sm font-bold block text-indigo-secondary">
                  {data.review_participation !== undefined ? `${Math.round(data.review_participation * 100)}%` : "N/A"}
                </span>
                <span className="text-[8px] uppercase tracking-wider text-indigo-on-surface-variant/50">Participation</span>
              </div>
            </div>
          </div>

          {/* Top Repositories Card */}
          <div className="md:col-span-12 bg-[#111111] border border-indigo-outline-variant/30 rounded-xl overflow-hidden flex flex-col">
            <div className="bg-[#050505] px-4 py-3 border-b border-[#222222] flex items-center justify-between">
              <span className="font-code text-xs text-indigo-on-surface-variant font-bold flex items-center gap-1.5">
                <span className="material-symbols-outlined text-sm text-indigo-primary">folder</span>
                repository_inventory.log
              </span>
              <span className="text-[10px] font-code text-indigo-on-surface-variant/50 uppercase">Public Repositories</span>
            </div>
            
            <div className="divide-y divide-[#222222]/40 font-code text-xs max-h-[320px] overflow-y-auto pr-1 scrollbar-thin">
              {data.repos && data.repos.length > 0 ? (
                data.repos.map((repo) => (
                  <div key={repo.full_name || repo} className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:bg-white/[0.01] transition-colors">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        {typeof repo === "string" ? (
                          <span onClick={() => navigate(`/dashboard?repo=${repo}`)} className="text-on-surface hover:text-indigo-primary transition-colors font-bold cursor-pointer">
                            {repo}
                          </span>
                        ) : (
                          <span onClick={() => navigate(`/dashboard?repo=${repo.full_name}`)} className="text-on-surface hover:text-indigo-primary transition-colors font-bold cursor-pointer">
                            {repo.name}
                          </span>
                        )}
                        {repo.url && (
                          <a href={repo.url} target="_blank" rel="noreferrer" className="text-indigo-on-surface-variant/40 hover:text-indigo-primary flex items-center">
                            <span className="material-symbols-outlined text-xs">open_in_new</span>
                          </a>
                        )}
                      </div>
                      {repo.full_name && (
                        <p className="text-[10px] text-indigo-on-surface-variant/60">@{repo.full_name}</p>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-4 text-[10px] text-indigo-on-surface-variant/85">
                      {repo.language && (
                        <div className="flex items-center gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-indigo-primary shrink-0"></span>
                          <span>{repo.language}</span>
                        </div>
                      )}
                      
                      {repo.stars !== undefined && (
                        <div className="flex items-center gap-1">
                          <span className="material-symbols-outlined text-[11px] text-indigo-tertiary">star</span>
                          <span>{repo.stars}</span>
                        </div>
                      )}

                      {repo.forks !== undefined && (
                        <div className="flex items-center gap-1">
                          <span className="material-symbols-outlined text-[11px] text-indigo-secondary">fork_left</span>
                          <span>{repo.forks}</span>
                        </div>
                      )}

                      {repo.updated_at && (
                        <span className="text-indigo-on-surface-variant/40">
                          {timeAgo(repo.updated_at) ? `updated ${timeAgo(repo.updated_at)}` : ""}
                        </span>
                      )}
                    </div>
                  </div>
                ))
              ) : (
                <div className="p-8 text-center text-indigo-on-surface-variant/40">
                  No public repositories metadata compiled.
                </div>
              )}
            </div>
          </div>

          {/* AI Developer Blurb */}
          <div className="md:col-span-12 bg-[#111111] border border-indigo-outline-variant/30 p-4 rounded-xl space-y-3">
            <h3 className="font-code text-xs text-indigo-primary font-bold uppercase tracking-wider flex items-center gap-1.5 select-none border-b border-indigo-outline-variant/20 pb-2">
              <span className="material-symbols-outlined text-sm text-indigo-primary">auto_awesome</span>
              AI Developer Summary
            </h3>
            {data.llm_summary ? (
              <p className="text-xs text-indigo-on-surface-variant font-code leading-relaxed bg-black/40 border border-[#222222] p-4 rounded-md">
                {data.llm_summary}
              </p>
            ) : (
              <div className="text-center py-4 font-code text-xs text-indigo-on-surface-variant/40 bg-black/40 border border-[#222222] p-4 rounded-md">
                No LLM configured on the server, AI summary blurb unavailable.
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
