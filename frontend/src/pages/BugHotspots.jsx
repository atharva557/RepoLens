import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { getJSON, postJSON } from "../lib/api";

const DEFAULT_REPO = "pallets/flask";

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

export default function BugHotspots() {
  const navigate = useNavigate();
  const repo = new URLSearchParams(window.location.search).get("repo") || DEFAULT_REPO;

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedRow, setSelectedRow] = useState(null);
  const [search, setSearch] = useState("");
  const [filterLevel, setFilterLevel] = useState("ALL");
  const [activity, setActivity] = useState(null);
  const [triggeringAnalyze, setTriggeringAnalyze] = useState(false);

  const loadHotspots = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      getJSON(`/repos/${repo}/hotspots?top=100`),
      getJSON(`/repos/${repo}/activity?recent=10`).catch(() => null),
    ])
      .then(([hotspotsData, activityData]) => {
        setData(hotspotsData);
        setActivity(activityData);
        if (hotspotsData.rows && hotspotsData.rows.length > 0) {
          setSelectedRow(hotspotsData.rows[0]);
        }
        setLoading(false);
      })
      .catch((e) => {
        setError(String(e));
        setLoading(false);
      });
  }, [repo]);

  useEffect(() => {
    loadHotspots();
  }, [loadHotspots]);

  const handleAnalyzeTrigger = async () => {
    setTriggeringAnalyze(true);
    try {
      const res = await postJSON("/analyze", { repo, refresh: true });
      navigate(`/loading?job=${res.job_id}&repo=${repo}&next=/hotspots`);
    } catch (e) {
      alert(`Analyze trigger failed: ${e.message}`);
      setTriggeringAnalyze(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-[#000000] text-on-surface">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-indigo-primary border-t-transparent rounded-full animate-spin mx-auto"></div>
          <p className="font-code text-label text-indigo-on-surface-variant uppercase tracking-widest animate-pulse">
            Analyzing repository hotspot files...
          </p>
        </div>
      </div>
    );
  }

  // Handle 404 or Not Analyzed State
  if (error && (error.includes("404") || error.includes("not found") || error.includes("not analyzed"))) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-[#000000] text-on-surface p-6">
        <div className="max-w-md w-full bg-[#111111] border border-indigo-outline-variant/30 p-8 text-center space-y-6 rounded-lg">
          <span className="material-symbols-outlined text-indigo-primary text-[64px]">explore_off</span>
          <div className="space-y-2">
            <h2 className="font-code text-heading-lg text-indigo-primary font-bold">No Hotspot Data</h2>
            <p className="text-xs text-indigo-on-surface-variant leading-relaxed">
              This repository has not been analyzed yet. Run a code hot-spot analysis to inspect bug risks.
            </p>
          </div>
          <button
            onClick={handleAnalyzeTrigger}
            disabled={triggeringAnalyze}
            className="w-full bg-indigo-primary hover:opacity-90 text-on-primary font-code font-bold py-3 rounded-md transition-all active:scale-95 disabled:opacity-50"
          >
            {triggeringAnalyze ? "TRIGGERING..." : "RUN INITIAL HOTSPOT ANALYSIS"}
          </button>
        </div>
      </div>
    );
  }

  // General error handler
  if (error) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-[#000000] text-on-surface p-6">
        <div className="max-w-md w-full bg-[#111111] border border-error/30 p-8 text-center space-y-4 rounded-lg">
          <span className="material-symbols-outlined text-error text-[54px]">warning</span>
          <h2 className="font-code text-heading-lg text-error font-bold">Error loading hotspots</h2>
          <p className="text-xs text-indigo-on-surface-variant leading-relaxed break-words">{error}</p>
          <button
            onClick={loadHotspots}
            className="w-full bg-indigo-primary hover:opacity-90 text-on-primary font-code font-bold py-2 rounded-md"
          >
            RETRY
          </button>
        </div>
      </div>
    );
  }

  const rows = data.rows || [];

  // Determine Risk Category client-side
  const getRiskCategory = (score) => {
    if (score >= 0.7) return { label: "Critical", color: "text-error border-error/20 bg-error/10", barColor: "bg-error" };
    if (score >= 0.4) return { label: "High", color: "text-indigo-tertiary border-indigo-tertiary/20 bg-indigo-tertiary/10", barColor: "bg-indigo-tertiary" };
    return { label: "Medium", color: "text-indigo-primary border-indigo-primary/20 bg-indigo-primary/10", barColor: "bg-indigo-primary" };
  };

  // Client-side statistics
  const totalHighRisk = rows.filter((r) => r.score >= 0.7).length;
  const avgRiskScore = rows.length > 0 ? (rows.reduce((acc, r) => acc + r.score, 0) / rows.length) * 100 : 0;
  
  // Check if any row has ML opinion
  const hasMLColumn = rows.some((r) => r.ml_prob !== undefined && r.ml_prob !== null);

  // Search and Filter Rows
  const filteredRows = rows.filter((r) => {
    const matchesSearch = r.path.toLowerCase().includes(search.toLowerCase());
    
    if (filterLevel === "ALL") return matchesSearch;
    const cat = getRiskCategory(r.score).label.toUpperCase();
    return matchesSearch && cat === filterLevel;
  });

  // Check if a row has score / ml_prob disagreement
  const checkDisagreement = (row) => {
    if (row.ml_prob === undefined || row.ml_prob === null) return false;
    // Disagreement if difference is > 0.4
    return Math.abs(row.score - row.ml_prob) > 0.4;
  };

  return (
    <div className="min-h-screen bg-[#000000] text-on-surface pb-12 font-body selection:bg-indigo-primary selection:text-on-primary">
      <main className="pt-8 px-margin-mobile md:px-margin-desktop grid grid-cols-12 gap-gutter max-w-[1920px] mx-auto space-y-6">
        
        {/* Header Section */}
        <div className="col-span-12 space-y-2">
          <h1 className="font-headline-lg text-3xl font-bold bg-gradient-to-r from-indigo-primary to-indigo-secondary bg-clip-text text-transparent inline-block">
            Bug Hotspots
          </h1>
          <p className="font-body-lg text-sm text-indigo-on-surface-variant max-w-3xl leading-relaxed">
            Advanced static profiling ranking files based on bug history density, cycle complexities, developer authors count, and churn.
          </p>
        </div>

        {/* Key Risk Metrics */}
        <div className="col-span-12 grid grid-cols-1 sm:grid-cols-3 gap-gutter">
          <div className="bg-[#111111] border border-[#222222] p-4 rounded-xl hover:border-[#333333] transition-all">
            <p className="font-label-caps text-[10px] text-indigo-on-surface-variant uppercase tracking-widest">Total High Risk Files</p>
            <h2 className="font-display-lg text-4xl font-bold mt-2 text-error">{totalHighRisk}</h2>
            <div className="flex items-center gap-1 mt-2 text-error text-xs">
              <span className="material-symbols-outlined text-xs">warning</span>
              <span>score threshold &gt;= 0.70</span>
            </div>
          </div>
          <div className="bg-[#111111] border border-[#222222] p-4 rounded-xl hover:border-[#333333] transition-all">
            <p className="font-label-caps text-[10px] text-indigo-on-surface-variant uppercase tracking-widest">Average Risk Score</p>
            <h2 className="font-display-lg text-4xl font-bold mt-2 text-on-surface">{avgRiskScore.toFixed(1)}</h2>
            <div className="flex items-center gap-1 mt-2 text-indigo-primary text-xs">
              <span className="material-symbols-outlined text-xs">trending_flat</span>
              <span>Across {rows.length} scored files</span>
            </div>
          </div>
          <div className="bg-[#111111] border border-[#222222] p-4 rounded-xl hover:border-[#333333] transition-all">
            <p className="font-label-caps text-[10px] text-indigo-on-surface-variant uppercase tracking-widest">Repository Analyzed</p>
            <h2 className="font-display-lg text-2xl font-code truncate font-bold mt-3.5 text-indigo-secondary">
              {repo}
            </h2>
            <div className="flex items-center gap-1 mt-2.5 text-indigo-on-surface-variant/60 text-xs">
              <span className="material-symbols-outlined text-xs">calendar_today</span>
              <span>Generated {timeAgo(data.generated_at)}</span>
            </div>
          </div>
        </div>

        {/* Main Content Split: Table and Detail Panel */}
        <div className="col-span-12 grid grid-cols-1 lg:grid-cols-12 gap-gutter items-start">
          {/* Table Container */}
          <div className="lg:col-span-8 bg-[#111111] border border-[#222222] rounded-xl overflow-hidden flex flex-col">
            {/* Header filters */}
            <div className="bg-[#050505] px-4 py-3 border-b border-[#222222] flex flex-col sm:flex-row justify-between items-center gap-3">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-indigo-primary"></span>
                <span className="font-code text-xs text-indigo-on-surface-variant font-bold">hotspot_matrix.log</span>
              </div>
              <div className="flex items-center gap-3 w-full sm:w-auto">
                <div className="relative flex-grow sm:flex-grow-0">
                  <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-indigo-on-surface-variant text-[14px]">search</span>
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search file paths..."
                    className="bg-[#0a0a0a] border border-[#222222] rounded px-8 py-1 font-code text-xs focus:outline-none focus:border-indigo-primary w-full sm:w-56 text-on-surface placeholder:text-indigo-on-surface-variant/40"
                  />
                </div>
                <select
                  value={filterLevel}
                  onChange={(e) => setFilterLevel(e.target.value)}
                  className="bg-[#0a0a0a] border border-[#222222] rounded px-3 py-1 font-code text-xs focus:outline-none focus:border-indigo-primary text-on-surface"
                >
                  <option value="ALL">ALL LEVELS</option>
                  <option value="CRITICAL">CRITICAL</option>
                  <option value="HIGH">HIGH</option>
                  <option value="MEDIUM">MEDIUM</option>
                </select>
              </div>
            </div>

            {/* Scroller table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-surface-container-low border-b border-[#222222] text-[10px] text-indigo-on-surface-variant font-code font-bold uppercase select-none">
                    <th className="px-4 py-3 w-16">Rank</th>
                    <th className="px-4 py-3">File path</th>
                    <th className="px-4 py-3 w-28">Risk Level</th>
                    <th className="px-4 py-3 w-40">Risk Score</th>
                    {hasMLColumn && <th className="px-4 py-3 w-32">ML Probability</th>}
                  </tr>
                </thead>
                <tbody className="text-xs font-code">
                  {filteredRows.length === 0 ? (
                    <tr>
                      <td colSpan={hasMLColumn ? 5 : 4} className="p-8 text-center text-indigo-on-surface-variant">
                        No hotspot items match active query criteria.
                      </td>
                    </tr>
                  ) : (
                    filteredRows.map((row) => {
                      const rank = rows.findIndex((r) => r.path === row.path) + 1;
                      const isSelected = selectedRow && selectedRow.path === row.path;
                      const risk = getRiskCategory(row.score);
                      const discrepancy = checkDisagreement(row);

                      return (
                        <tr
                          key={row.path}
                          onClick={() => setSelectedRow(row)}
                          className={`border-b border-[#222222]/40 hover:bg-white/[0.03] transition-colors cursor-pointer ${
                            isSelected ? "bg-indigo-primary/[0.04] border-l-2 border-l-indigo-primary" : ""
                          }`}
                        >
                          <td className="px-4 py-3.5 text-indigo-on-surface-variant font-bold">
                            {rank.toString().padStart(2, "0")}
                          </td>
                          <td className="px-4 py-3.5 pr-2">
                            <div className="flex flex-col">
                              <span className="text-on-surface font-medium truncate max-w-xs md:max-w-md" title={row.path}>
                                {row.path}
                              </span>
                              
                              {/* Component level mini-bars */}
                              {row.components && (
                                <div className="flex items-center gap-1.5 mt-1 select-none">
                                  <div className="flex gap-0.5" title={`bug: ${row.components.bug?.toFixed(2)}, churn: ${row.components.churn?.toFixed(2)}, authors: ${row.components.authors?.toFixed(2)}, complexity: ${row.components.complexity?.toFixed(2)}`}>
                                    <div className="w-4 h-1 bg-error/20 overflow-hidden"><div className="h-full bg-error" style={{ width: `${(row.components.bug || 0) * 100}%` }}></div></div>
                                    <div className="w-4 h-1 bg-indigo-tertiary/20 overflow-hidden"><div className="h-full bg-indigo-tertiary" style={{ width: `${(row.components.churn || 0) * 100}%` }}></div></div>
                                    <div className="w-4 h-1 bg-green-500/20 overflow-hidden"><div className="h-full bg-green-500" style={{ width: `${(row.components.authors || 0) * 100}%` }}></div></div>
                                    <div className="w-4 h-1 bg-indigo-primary/20 overflow-hidden"><div className="h-full bg-indigo-primary" style={{ width: `${(row.components.complexity || 0) * 100}%` }}></div></div>
                                  </div>
                                  <span className="text-[9px] text-indigo-on-surface-variant/40 leading-none">weights</span>
                                </div>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-3.5">
                            <span className={`px-2 py-0.5 border text-[9px] font-bold uppercase rounded-sm select-none ${risk.color}`}>
                              {risk.label}
                            </span>
                          </td>
                          <td className="px-4 py-3.5">
                            <div className="flex items-center gap-3">
                              <div className="w-16 h-1 bg-[#222222] rounded-full overflow-hidden shrink-0">
                                <div className={`h-full ${risk.barColor} rounded-full`} style={{ width: `${row.score * 100}%` }}></div>
                              </div>
                              <span className="text-on-surface font-bold font-code">{Math.round(row.score * 100)}</span>
                            </div>
                          </td>
                          {hasMLColumn && (
                            <td className="px-4 py-3.5">
                              <div className="flex items-center gap-1.5 font-code">
                                <span className={discrepancy ? "text-error font-bold" : "text-on-surface-variant"}>
                                  {row.ml_prob !== null ? `${Math.round(row.ml_prob * 100)}%` : "N/A"}
                                </span>
                                {discrepancy && (
                                  <span className="material-symbols-outlined text-xs text-error font-bold select-none" title="Heuristic and ML disagree significantly">
                                    warning
                                  </span>
                                )}
                              </div>
                            </td>
                          )}
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
            
            {/* Table pagination footer */}
            <div className="p-3 bg-[#0a0a0a] border-t border-[#222222] flex justify-between items-center text-[10px] font-code text-indigo-on-surface-variant select-none">
              <span>Scored {filteredRows.length} files matching query</span>
              <span className="uppercase">Heuristics active</span>
            </div>
          </div>

          {/* Side Panel: File Insights (Deep Metrics) */}
          <aside className="lg:col-span-4 h-full">
            {selectedRow ? (
              <div className="bg-[#111111] border border-[#222222] rounded-xl flex flex-col overflow-hidden">
                <div className="bg-[#050505] px-4 py-3 border-b border-[#222222] flex items-center justify-between">
                  <span className="font-code text-xs text-indigo-primary font-bold">Deep File Analysis</span>
                  <span className="material-symbols-outlined text-indigo-on-surface-variant text-[16px] cursor-pointer hover:text-on-surface" onClick={() => setSelectedRow(null)}>
                    close
                  </span>
                </div>
                
                <div className="p-4 space-y-6">
                  {/* File Metadata */}
                  <div className="space-y-1">
                    <p className="font-code text-[9px] text-indigo-on-surface-variant uppercase tracking-wider font-bold">// PATH</p>
                    <h4 className="font-code text-xs text-on-surface break-all bg-black/40 border border-[#222222] p-2.5 rounded-sm select-all">
                      {selectedRow.path}
                    </h4>
                  </div>

                  {/* Quantitative metrics cards */}
                  <div className="grid grid-cols-2 gap-3">
                    <div className="bg-[#181818] border border-[#222222] p-3 rounded-lg space-y-1">
                      <p className="text-[9px] font-code font-bold text-indigo-on-surface-variant uppercase">Complexity Code</p>
                      <p className="text-xl font-bold font-code text-on-surface">{selectedRow.raw.cyclomatic || selectedRow.raw.complexity || "N/A"}</p>
                      <p className="text-[9px] font-code text-indigo-on-surface-variant/50 leading-tight">Cyclomatic rating</p>
                    </div>
                    <div className="bg-[#181818] border border-[#222222] p-3 rounded-lg space-y-1">
                      <p className="text-[9px] font-code font-bold text-indigo-on-surface-variant uppercase">Change Commits</p>
                      <p className="text-xl font-bold font-code text-on-surface">{selectedRow.raw.commits || "N/A"}</p>
                      <p className="text-[9px] font-code text-indigo-on-surface-variant/50 leading-tight">{selectedRow.raw.churn_lines ? `${selectedRow.raw.churn_lines} lines churned` : "Historical frequency"}</p>
                    </div>
                  </div>

                  {/* Explanatory Reasons Block */}
                  {selectedRow.reasons && selectedRow.reasons.length > 0 && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-1.5">
                        <span className="material-symbols-outlined text-sm text-indigo-primary">auto_awesome</span>
                        <span className="font-code text-[10px] text-indigo-primary uppercase font-bold tracking-wider">AI Diagnostic Factors</span>
                      </div>
                      <div className="space-y-2">
                        {selectedRow.reasons.map((reason, idx) => (
                          <div key={idx} className="p-2.5 bg-indigo-primary/5 border-l border-l-indigo-primary font-code text-[11px] leading-relaxed text-on-surface/90">
                            {reason}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Recent Activity Context list */}
                  {activity && activity.recent_commits && (
                    <div className="space-y-3 font-code">
                      <span className="text-[9px] text-indigo-on-surface-variant uppercase font-bold tracking-wider block">// RECENT RISKY CHANGES IN REPO</span>
                      <div className="divide-y divide-[#222222] max-h-[140px] overflow-y-auto pr-1 scrollbar-thin">
                        {activity.recent_commits.slice(0, 3).map((c) => (
                          <div key={c.sha} className="py-2 text-[10px] leading-tight space-y-0.5">
                            <div className="flex justify-between items-start gap-1">
                              <span className="text-on-surface font-medium truncate">{c.subject}</span>
                              {c.is_bugfix && <span className="text-error font-bold shrink-0 text-[8px] border border-error/30 px-1 rounded-sm">FIX</span>}
                            </div>
                            <div className="text-[9px] text-indigo-on-surface-variant/40 flex justify-between">
                              <span>author: {c.author}</span>
                              <span>{c.sha.slice(0, 7)}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="bg-[#111111] border border-[#222222] rounded-xl p-8 text-center space-y-3">
                <span className="material-symbols-outlined text-indigo-on-surface-variant opacity-30 text-[48px]">input</span>
                <p className="text-xs text-indigo-on-surface-variant font-code leading-relaxed">
                  Select a hotspot file row in the matrix list to profile structural code complexity metrics and reasons.
                </p>
              </div>
            )}
          </aside>
        </div>
      </main>
    </div>
  );
}
