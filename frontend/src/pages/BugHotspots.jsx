import { useEffect, useState, useCallback, useRef } from "react";
import { useNavigate, Link } from "react-router-dom";
import { getJSON, postJSON } from "../lib/api";
import { loadRepoSettings } from "../lib/settings";

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

const PAGE_SIZE = 10;

export default function BugHotspots() {
  const navigate = useNavigate();
  const repo = new URLSearchParams(window.location.search).get("repo");

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedRow, setSelectedRow] = useState(null);
  const [search, setSearch] = useState("");
  const [filterLevel, setFilterLevel] = useState("ALL");
  const [activity, setActivity] = useState(null);
  const [triggeringAnalyze, setTriggeringAnalyze] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageTransition, setPageTransition] = useState(false);
  const asideRef = useRef(null);
  const tableTopRef = useRef(null);

  const handleRowClick = (row) => {
    setSelectedRow(row);
    if (window.innerWidth < 1024 && asideRef.current) {
      setTimeout(() => {
        asideRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 50);
    }
  };

  const loadHotspots = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      getJSON(`/repos/${repo}/hotspots?top=50`, { ttl: 60000 }),
      getJSON(`/repos/${repo}/activity?recent=10`, { ttl: 60000 }).catch(() => null),
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
    if (repo) loadHotspots();
    else setLoading(false);
  }, [loadHotspots, repo]);

  // Reset to page 1 whenever search or filter changes
  useEffect(() => {
    setCurrentPage(1);
  }, [search, filterLevel]);

  const handleAnalyzeTrigger = async () => {
    setTriggeringAnalyze(true);
    try {
      const settings = loadRepoSettings(repo);
      const res = await postJSON("/analyze", { repo, refresh: true, max_commits: settings.max_commits, top: settings.top });
      navigate(`/loading?job=${res.job_id}&repo=${repo}&next=/hotspots`);
    } catch (e) {
      alert(`Analyze trigger failed: ${e.message}`);
      setTriggeringAnalyze(false);
    }
  };

  if (!repo) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface p-6 relative overflow-hidden">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-primary/5 rounded-full blur-[100px] pointer-events-none"></div>
        <div className="relative w-full max-w-[460px] h-auto p-10 rounded-3xl bg-surface-container-lowest/60 backdrop-blur-xl border border-outline-variant/40 shadow-2xl shadow-primary/10 transition-all duration-300 hover:scale-[1.02] text-center flex flex-col items-center gap-6">
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
            className="w-full bg-primary hover:bg-primary-container text-on-primary font-code font-bold py-3.5 rounded-xl transition-all duration-300 active:scale-95 text-center flex items-center justify-center gap-2 mt-2 shadow-lg shadow-primary/20"
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
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-primary border-t-transparent rounded-full motion-safe:animate-spin mx-auto"></div>
          <p className="font-code text-label text-on-surface-variant uppercase tracking-widest animate-pulse">
            Analyzing repository hotspot files...
          </p>
        </div>
      </div>
    );
  }

  if (error && (error.includes("404") || error.includes("not found") || error.includes("not analyzed"))) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface p-6">
        <div className="max-w-[28rem] w-full bg-surface-container border border-outline-variant/30 p-8 text-center space-y-6 rounded-lg">
          <span className="material-symbols-outlined text-primary text-[64px]">explore_off</span>
          <div className="space-y-2">
            <h2 className="font-code text-heading-lg text-primary font-bold">No Hotspot Data</h2>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              This repository has not been analyzed yet. Run a code hot-spot analysis to inspect bug risks.
            </p>
          </div>
          <button
            onClick={handleAnalyzeTrigger}
            disabled={triggeringAnalyze}
            className="w-full bg-primary hover:opacity-90 text-on-primary font-code font-bold py-3 rounded-md transition-all active:scale-95 disabled:opacity-50"
          >
            {triggeringAnalyze ? "TRIGGERING..." : "RUN INITIAL HOTSPOT ANALYSIS"}
          </button>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface p-6">
        <div className="max-w-[28rem] w-full bg-surface-container border border-error/30 p-8 text-center space-y-4 rounded-lg">
          <span className="material-symbols-outlined text-error text-[54px]">warning</span>
          <h2 className="font-code text-heading-lg text-error font-bold">Error loading hotspots</h2>
          <p className="text-xs text-on-surface-variant leading-relaxed break-words">{error}</p>
          <button onClick={loadHotspots} className="w-full bg-primary hover:opacity-90 text-on-primary font-code font-bold py-2 rounded-md">
            RETRY
          </button>
        </div>
      </div>
    );
  }

  const rows = data.rows || [];

  const getRiskCategory = (score) => {
    if (score >= 0.7) return { label: "Critical", color: "text-error border-error/20 bg-error/10", barColor: "bg-error" };
    if (score >= 0.4) return { label: "High", color: "text-tertiary border-tertiary/20 bg-tertiary/10", barColor: "bg-tertiary" };
    return { label: "Medium", color: "text-primary border-primary/20 bg-primary/10", barColor: "bg-primary" };
  };

  const totalHighRisk = rows.filter((r) => r.score >= 0.7).length;
  const avgRiskScore = rows.length > 0 ? (rows.reduce((acc, r) => acc + r.score, 0) / rows.length) * 100 : 0;
  const hasMLColumn = rows.some((r) => r.ml_prob !== undefined && r.ml_prob !== null);

  // All filtered rows (search + risk filter applied to full dataset)
  const filteredRows = rows.filter((r) => {
    const matchesSearch = r.path.toLowerCase().includes(search.toLowerCase());
    if (filterLevel === "ALL") return matchesSearch;
    const cat = getRiskCategory(r.score).label.toUpperCase();
    return matchesSearch && cat === filterLevel;
  });

  // Pagination derived values
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const pageStart = (safePage - 1) * PAGE_SIZE;       // 0-based index into filteredRows
  const pageEnd = pageStart + PAGE_SIZE;
  const pageRows = filteredRows.slice(pageStart, pageEnd);

  const checkDisagreement = (row) => {
    if (row.ml_prob === undefined || row.ml_prob === null) return false;
    return Math.abs(row.score - row.ml_prob) > 0.4;
  };

  // Animated page change
  const goToPage = (next) => {
    if (next < 1 || next > totalPages) return;
    setPageTransition(true);
    setTimeout(() => {
      setCurrentPage(next);
      setPageTransition(false);
      // Scroll table back to top on page change
      if (tableTopRef.current) {
        tableTopRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }, 120);
  };

  // Keep selectedRow in sync: if selected row is not on current page, keep it visible in the panel
  // (do NOT deselect — requirement says "maintain selected file if it still exists")

  return (
    <div className="min-h-screen bg-background text-on-surface pb-12 font-body selection:bg-primary selection:text-on-primary">
      <main className="pt-8 px-margin-mobile md:px-margin-desktop grid grid-cols-12 gap-gutter max-w-[1920px] mx-auto space-y-6">

        {/* Header */}
        <div className="col-span-12 space-y-2">
          <h1 className="font-headline-lg text-3xl font-bold bg-gradient-to-r from-primary to-secondary bg-clip-text text-transparent inline-block">
            Bug Hotspots
          </h1>
          <p className="font-body-lg text-sm text-on-surface-variant max-w-3xl leading-relaxed">
            Advanced static profiling ranking files based on bug history density, cycle complexities, developer authors count, and churn.
          </p>
        </div>

        {/* Key Risk Metrics */}
        <div className="col-span-12 grid grid-cols-1 sm:grid-cols-3 gap-gutter">
          <div className="bg-surface-container border border-outline-variant/40 border-t-primary/40 p-4 rounded-xl hover:border-outline-variant/60 hover:border-t-primary/40 transition-all">
            <p className="font-label-caps text-[10px] text-on-surface-variant uppercase tracking-widest">Total High Risk Files</p>
            <h2 className="font-display-lg text-4xl font-bold mt-2 text-error">{totalHighRisk}</h2>
            <div className="flex items-center gap-1 mt-2 text-error text-xs">
              <span className="material-symbols-outlined text-xs">warning</span>
              <span>score threshold &gt;= 0.70</span>
            </div>
          </div>
          <div className="bg-surface-container border border-outline-variant/40 border-t-primary/40 p-4 rounded-xl hover:border-outline-variant/60 hover:border-t-primary/40 transition-all">
            <p className="font-label-caps text-[10px] text-on-surface-variant uppercase tracking-widest">Average Risk Score</p>
            <h2 className="font-display-lg text-4xl font-bold mt-2 text-on-surface">{avgRiskScore.toFixed(1)}</h2>
            <div className="flex items-center gap-1 mt-2 text-primary text-xs">
              <span className="material-symbols-outlined text-xs">trending_flat</span>
              <span>Across {rows.length} scored files</span>
            </div>
          </div>
          <div className="bg-surface-container border border-outline-variant/40 border-t-primary/40 p-4 rounded-xl hover:border-outline-variant/60 hover:border-t-primary/40 transition-all">
            <p className="font-label-caps text-[10px] text-on-surface-variant uppercase tracking-widest">Repository Analyzed</p>
            <h2 className="font-display-lg text-2xl font-code truncate font-bold mt-3.5 text-secondary">{repo}</h2>
            <div className="flex items-center gap-1 mt-2.5 text-on-surface-variant/60 text-xs">
              <span className="material-symbols-outlined text-xs">calendar_today</span>
              <span>Generated {timeAgo(data.generated_at)}</span>
            </div>
          </div>
        </div>

        {/* Main split: table + detail panel */}
        <div className="col-span-12 grid grid-cols-1 lg:grid-cols-12 gap-gutter items-start">

          {/* ── Table ── */}
          <div className="lg:col-span-8 bg-surface-container border border-outline-variant/40 border-t-primary/40 rounded-xl overflow-hidden flex flex-col">

            {/* Filters bar */}
            <div ref={tableTopRef} className="bg-background px-4 py-3 border-b border-outline-variant/40 flex flex-col sm:flex-row justify-between items-center gap-3">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-primary"></span>
                <span className="font-code text-xs text-on-surface-variant font-bold">hotspot_matrix.log</span>
              </div>
              <div className="flex items-center gap-3 w-full sm:w-auto">
                <div className="relative flex-grow sm:flex-grow-0">
                  <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-on-surface-variant text-[14px]">search</span>
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search file paths..."
                    className="bg-background border border-outline-variant/40 rounded px-8 py-1 font-code text-xs focus:outline-none focus:border-primary w-full sm:w-56 text-on-surface placeholder:text-on-surface-variant/40"
                  />
                </div>
                <select
                  value={filterLevel}
                  onChange={(e) => setFilterLevel(e.target.value)}
                  className="bg-background border border-outline-variant/40 rounded px-3 py-1 font-code text-xs focus:outline-none focus:border-primary text-on-surface"
                >
                  <option value="ALL">ALL LEVELS</option>
                  <option value="CRITICAL">CRITICAL</option>
                  <option value="HIGH">HIGH</option>
                  <option value="MEDIUM">MEDIUM</option>
                </select>
              </div>
            </div>

            {/* Scrollable table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-surface-container-low border-b border-outline-variant/40 text-[10px] text-on-surface-variant font-code font-bold uppercase select-none">
                    <th className="px-4 py-3 w-16">Rank</th>
                    <th className="px-4 py-3">File path</th>
                    <th className="px-4 py-3 w-28">Risk Level</th>
                    <th className="px-4 py-3 w-40">Risk Score</th>
                    {hasMLColumn && <th className="px-4 py-3 w-32">ML Probability</th>}
                  </tr>
                </thead>
                <tbody
                  className="text-xs font-code"
                  style={{
                    opacity: pageTransition ? 0 : 1,
                    transition: "opacity 0.12s ease",
                  }}
                >
                  {pageRows.length === 0 ? (
                    <tr>
                      <td colSpan={hasMLColumn ? 5 : 4} className="p-8 text-center text-on-surface-variant">
                        No hotspot items match active query criteria.
                      </td>
                    </tr>
                  ) : (
                    pageRows.map((row) => {
                      // Global rank = position in the full (unfiltered) rows array
                      const globalRank = rows.findIndex((r) => r.path === row.path) + 1;
                      const isSelected = selectedRow && selectedRow.path === row.path;
                      const risk = getRiskCategory(row.score);
                      const discrepancy = checkDisagreement(row);

                      return (
                        <tr
                          key={row.path}
                          onClick={() => handleRowClick(row)}
                          className={`border-b border-outline-variant/40/40 transition-all duration-200 cursor-pointer ${isSelected
                            ? "bg-primary/[0.08] border-l-[3px] border-l-primary shadow-inner"
                            : "hover:bg-white/[0.03] border-l-[3px] border-l-transparent"
                            }`}
                        >
                          <td className="px-4 py-3.5 text-on-surface-variant font-bold">
                            {/* Global numbering — continues across pages */}
                            {globalRank.toString().padStart(2, "0")}
                          </td>
                          <td className="px-4 py-3.5 pr-2">
                            <div className="flex flex-col">
                              <span className="text-on-surface font-medium truncate max-w-[20rem] md:max-w-[28rem]" title={row.path}>
                                {row.path}
                              </span>
                              {row.components && (
                                <div className="flex items-center gap-1.5 mt-1 select-none">
                                  <div className="flex gap-0.5" title={`bug: ${row.components.bug?.toFixed(2)}, churn: ${row.components.churn?.toFixed(2)}, authors: ${row.components.authors?.toFixed(2)}, complexity: ${row.components.complexity?.toFixed(2)}`}>
                                    <div className="w-4 h-1 bg-error/20 overflow-hidden"><div className="h-full bg-error" style={{ width: `${(row.components.bug || 0) * 100}%` }}></div></div>
                                    <div className="w-4 h-1 bg-tertiary/20 overflow-hidden"><div className="h-full bg-tertiary" style={{ width: `${(row.components.churn || 0) * 100}%` }}></div></div>
                                    <div className="w-4 h-1 bg-green-500/20 overflow-hidden"><div className="h-full bg-green-500" style={{ width: `${(row.components.authors || 0) * 100}%` }}></div></div>
                                    <div className="w-4 h-1 bg-primary/20 overflow-hidden"><div className="h-full bg-primary" style={{ width: `${(row.components.complexity || 0) * 100}%` }}></div></div>
                                  </div>
                                  <span className="text-[9px] text-on-surface-variant/40 leading-none">weights</span>
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
                              <div className="w-16 h-1 bg-surface-container-highest rounded-full overflow-hidden shrink-0">
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

            {/* ── Pagination footer ── */}
            <div className="border-t border-outline-variant/40 bg-background">
              {/* Row count summary */}
              <div className="px-4 pt-3 pb-1 flex justify-between items-center text-[10px] font-code text-on-surface-variant select-none">
                <span>
                  {filteredRows.length === 0
                    ? "No results"
                    : `Showing ${pageStart + 1}–${Math.min(pageEnd, filteredRows.length)} of ${filteredRows.length} hotspot${filteredRows.length !== 1 ? "s" : ""}`}
                </span>
                <span className="uppercase">Heuristics active</span>
              </div>

              {/* Pagination controls */}
              {totalPages > 1 && (
                <div className="px-4 pb-3 pt-2 flex items-center justify-between gap-3">
                  {/* Previous */}
                  <button
                    onClick={() => goToPage(safePage - 1)}
                    disabled={safePage <= 1}
                    className={`
                      flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-code text-[11px] font-bold
                      border transition-all duration-150 select-none
                      ${safePage <= 1
                        ? "border-outline-variant/40 text-on-surface-variant/30 cursor-not-allowed"
                        : "border-outline-variant/60 text-on-surface hover:bg-white/[0.05] hover:border-primary/40 active:scale-95 cursor-pointer"}
                    `}
                  >
                    <span className="material-symbols-outlined text-[14px]">chevron_left</span>
                    Previous
                  </button>

                  {/* Page pills */}
                  <div className="flex items-center gap-1.5 font-code text-[11px] select-none">
                    {/* Always show first page */}
                    {safePage > 3 && (
                      <>
                        <button
                          onClick={() => goToPage(1)}
                          className="w-7 h-7 rounded-md border border-outline-variant/60 text-on-surface-variant hover:border-primary/40 hover:text-on-surface transition-all text-[10px]"
                        >
                          1
                        </button>
                        {safePage > 4 && (
                          <span className="text-on-surface-variant/40 px-1">…</span>
                        )}
                      </>
                    )}

                    {/* Window of pages around current */}
                    {Array.from({ length: totalPages }, (_, i) => i + 1)
                      .filter((p) => p >= safePage - 1 && p <= safePage + 1)
                      .map((p) => (
                        <button
                          key={p}
                          onClick={() => goToPage(p)}
                          className={`
                            w-7 h-7 rounded-md border text-[10px] font-bold transition-all active:scale-95
                            ${p === safePage
                              ? "bg-primary border-primary text-on-primary shadow-sm shadow-primary/30"
                              : "border-outline-variant/60 text-on-surface-variant hover:border-primary/40 hover:text-on-surface"}
                          `}
                        >
                          {p}
                        </button>
                      ))}

                    {/* Always show last page */}
                    {safePage < totalPages - 2 && (
                      <>
                        {safePage < totalPages - 3 && (
                          <span className="text-on-surface-variant/40 px-1">…</span>
                        )}
                        <button
                          onClick={() => goToPage(totalPages)}
                          className="w-7 h-7 rounded-md border border-outline-variant/60 text-on-surface-variant hover:border-primary/40 hover:text-on-surface transition-all text-[10px]"
                        >
                          {totalPages}
                        </button>
                      </>
                    )}
                  </div>

                  {/* Next */}
                  <button
                    onClick={() => goToPage(safePage + 1)}
                    disabled={safePage >= totalPages}
                    className={`
                      flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-code text-[11px] font-bold
                      border transition-all duration-150 select-none
                      ${safePage >= totalPages
                        ? "border-outline-variant/40 text-on-surface-variant/30 cursor-not-allowed"
                        : "border-outline-variant/60 text-on-surface hover:bg-white/[0.05] hover:border-primary/40 active:scale-95 cursor-pointer"}
                    `}
                  >
                    Next
                    <span className="material-symbols-outlined text-[14px]">chevron_right</span>
                  </button>
                </div>
              )}

              {/* Single page: just show a minimal footer */}
              {totalPages <= 1 && filteredRows.length > 0 && (
                <div className="px-4 pb-3" />
              )}
            </div>
          </div>

          {/* ── Side Panel ── */}
          <aside ref={asideRef} className="lg:col-span-4 lg:sticky lg:top-24 transition-all duration-300 self-start w-full">
            {selectedRow ? (
              <div className="bg-surface-container border border-outline-variant/40 border-t-primary/40 rounded-xl flex flex-col overflow-hidden max-h-[calc(100vh-120px)]">
                <div className="bg-background px-4 py-3 border-b border-outline-variant/40 flex items-center justify-between shrink-0">
                  <span className="font-code text-xs text-primary font-bold">Deep File Analysis</span>
                  <span
                    className="material-symbols-outlined text-on-surface-variant text-[16px] cursor-pointer hover:text-on-surface"
                    onClick={() => setSelectedRow(null)}
                  >
                    close
                  </span>
                </div>

                <div className="p-4 space-y-6 overflow-y-auto scrollbar-thin">
                  <div className="space-y-1">
                    <p className="font-code text-[9px] text-on-surface-variant uppercase tracking-wider font-bold">PATH</p>
                    <h4 className="font-code text-xs text-on-surface break-all bg-black/40 border border-outline-variant/40 p-2.5 rounded-sm select-all">
                      {selectedRow.path}
                    </h4>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="bg-surface-container-high border border-outline-variant/40 border-t-primary/40 p-3 rounded-lg space-y-1">
                      <p className="text-[9px] font-code font-bold text-on-surface-variant uppercase">
                        {selectedRow.raw.cyclomatic != null ? "Cyclomatic Code" : "Lines of Code"}
                      </p>
                      <p className="text-xl font-bold font-code text-on-surface">
                        {selectedRow.raw.cyclomatic ?? selectedRow.raw.loc ?? "N/A"}
                      </p>
                      <p className="text-[9px] font-code text-on-surface-variant/50 leading-tight">
                        {selectedRow.raw.cyclomatic != null ? "Cyclomatic rating" : "Size proxy"}
                      </p>
                    </div>
                    <div className="bg-surface-container-high border border-outline-variant/40 border-t-primary/40 p-3 rounded-lg space-y-1">
                      <p className="text-[9px] font-code font-bold text-on-surface-variant uppercase">Change Commits</p>
                      <p className="text-xl font-bold font-code text-on-surface">{selectedRow.raw.commits || "N/A"}</p>
                      <p className="text-[9px] font-code text-on-surface-variant/50 leading-tight">
                        {selectedRow.raw.churn_lines ? `${selectedRow.raw.churn_lines} lines churned` : "Historical frequency"}
                      </p>
                    </div>
                  </div>

                  {selectedRow.reasons && selectedRow.reasons.length > 0 && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-1.5">
                        <span className="material-symbols-outlined text-sm text-primary">auto_awesome</span>
                        <span className="font-code text-[10px] text-primary uppercase font-bold tracking-wider">AI Diagnostic Factors</span>
                      </div>
                      <div className="space-y-2">
                        {selectedRow.reasons.map((reason, idx) => (
                          <div key={idx} className="p-2.5 bg-primary/5 border-l border-l-primary font-code text-[11px] leading-relaxed text-on-surface/90">
                            {reason}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {activity && activity.recent_commits && (
                    <div className="space-y-3 font-code">
                      <span className="text-[9px] text-on-surface-variant uppercase font-bold tracking-wider block">RECENT RISKY CHANGES IN REPO</span>
                      <div className="divide-y divide-[#222222] max-h-[140px] overflow-y-auto pr-1 scrollbar-thin">
                        {activity.recent_commits.slice(0, 3).map((c) => (
                          <div key={c.sha} className="py-2 text-[10px] leading-tight space-y-0.5">
                            <div className="flex justify-between items-start gap-1">
                              <span className="text-on-surface font-medium truncate">{c.subject}</span>
                              {c.is_bugfix && (
                                <span className="text-error font-bold shrink-0 text-[8px] border border-error/30 px-1 rounded-sm">FIX</span>
                              )}
                            </div>
                            <div className="text-[9px] text-on-surface-variant/40 flex justify-between">
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
              <div className="bg-surface-container border border-outline-variant/40 border-t-primary/40 rounded-xl p-8 text-center space-y-3">
                <span className="material-symbols-outlined text-on-surface-variant opacity-30 text-[48px]">input</span>
                <p className="text-xs text-on-surface-variant font-code leading-relaxed">
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
