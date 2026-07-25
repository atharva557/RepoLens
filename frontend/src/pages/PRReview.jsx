import { useEffect, useState, useCallback, useRef } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { getJSON, isNotFound, postJSON } from "../lib/api";

function parsePrInput(input) {
  let cleaned = input.trim();
  if (cleaned.includes("github.com/")) {
    const parts = cleaned.split("github.com/");
    if (parts.length > 1) {
      const pathParts = parts[1].split("/");
      // owner/repo/pull/42
      if (pathParts.length >= 4 && pathParts[2] === "pull") {
        return { repo: `${pathParts[0]}/${pathParts[1]}`, pr: pathParts[3] };
      }
    }
  }
  if (cleaned.includes("#")) {
    const [repo, pr] = cleaned.split("#");
    return { repo, pr };
  }
  return null;
}

function SimpleMarkdown({ text }) {
  if (!text) return null;
  const lines = text.split("\n");
  
  return (
    <div className="space-y-3 font-body text-[13px] leading-relaxed text-on-surface">
      {lines.map((line, idx) => {
        if (line.startsWith("### ")) {
          return <h3 key={idx} className="text-lg font-bold text-on-surface mt-4 mb-2">{formatInline(line.slice(4))}</h3>;
        } else if (line.startsWith("## ")) {
          return <h2 key={idx} className="text-xl font-bold text-primary mt-5 mb-3">{formatInline(line.slice(3))}</h2>;
        } else if (line.startsWith("- ")) {
          return (
            <div key={idx} className="flex gap-2 items-start pl-2">
              <span className="text-primary mt-1 text-[10px]">■</span>
              <span>{formatInline(line.slice(2))}</span>
            </div>
          );
        } else if (line.trim() === "") {
          return <div key={idx} className="h-2"></div>;
        } else {
          return <p key={idx}>{formatInline(line)}</p>;
        }
      })}
    </div>
  );
}

function formatInline(text) {
  // Simple bold formatting
  const parts = text.split(/(\*\*.*?\*\*)/g);
  return parts.map((part, idx) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={idx} className="text-on-surface font-bold">{part.slice(2, -2)}</strong>;
    }
    return <span key={idx}>{part}</span>;
  });
}

export default function PRReview() {
  const navigate = useNavigate();
  const location = useLocation();
  const searchParams = new URLSearchParams(location.search);
  const repo = searchParams.get("repo");
  const pr = searchParams.get("pr");
  
  const [inputVal, setInputVal] = useState("");
  const [report, setReport] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [tokenError, setTokenError] = useState(false);
  
  const [pollingJobId, setPollingJobId] = useState(null);
  const [jobPhase, setJobPhase] = useState(null);
  const [jobError, setJobError] = useState(null);
  const pollTimerRef = useRef(null);
  // pollJob reads the current report through a ref so it doesn't re-create
  // itself (and restart the poll loop) on every report update
  const reportRef = useRef(null);

  const [showMarkdown, setShowMarkdown] = useState(false);

  const applyReport = useCallback((data) => {
    reportRef.current = data;
    setReport(data);
  }, []);

  const fetchReport = useCallback(async (targetRepo, targetPr) => {
    setLoading(true);
    setError(null);
    setTokenError(false);
    try {
      const data = await getJSON(`/repos/${targetRepo}/pr-reviews/${targetPr}`);
      applyReport(data);
      setLoading(false);
    } catch (e) {
      if (isNotFound(e)) {
        // never reviewed yet — that's the normal first visit, not an error:
        // kick off the review and poll it
        triggerAnalysis(targetRepo, targetPr);
      } else {
        setError(e.message);
        setLoading(false);
      }
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchHistory = useCallback(async (targetRepo) => {
    try {
      const res = await getJSON(`/repos/${targetRepo}/pr-reviews`);
      setHistory(res.pr_reviews || []);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    // switching PRs must not keep showing the previous PR's report
    applyReport(null);
    setJobPhase(null);
    setJobError(null);
    if (repo && pr) {
      fetchReport(repo, pr);
    }
    // load the repo's reviewed-PR list whenever we know the repo — the input
    // screen shows it too, not just once a report is open
    if (repo) {
      fetchHistory(repo);
    }
    return () => clearTimeout(pollTimerRef.current);
  }, [repo, pr, fetchReport, fetchHistory, applyReport]);

  const triggerAnalysis = async (targetRepo, targetPr) => {
    setLoading(true);
    setError(null);
    setTokenError(false);
    setJobError(null);
    try {
      const res = await postJSON(`/repos/${targetRepo}/pr-reviews/${targetPr}`);
      setPollingJobId(res.job_id);
    } catch (e) {
      if (e.status === 400) {   // the API's "GITHUB_TOKEN is not configured"
        setTokenError(true);
      } else {
        setError(e.message);
      }
      setLoading(false);
    }
  };

  const pollJob = useCallback(async (jobId) => {
    try {
      const job = await getJSON(`/jobs/${jobId}`);
      if (job.status === "done") {
        setPollingJobId(null);
        setJobPhase(null);
        fetchReport(repo, pr);
        fetchHistory(repo);
      } else if (job.status === "failed") {
        setPollingJobId(null);
        setJobPhase(null);
        if (reportRef.current) {
          // keep the (preliminary or previous) report on screen and surface
          // the failure in the banner instead of replacing the whole page
          setJobError(job.error || "Analysis failed.");
        } else {
          setError(job.error || "Review failed.");
        }
        setLoading(false);
      } else {
        const p = job.progress;
        setJobPhase(p && p.phase ? (p.pct != null ? `${p.phase} — ${p.pct}%` : p.phase) : null);
        // the deterministic report is saved before the LLM phase runs — show
        // it as soon as it exists instead of spinning until the job ends
        if (!reportRef.current) {
          getJSON(`/repos/${repo}/pr-reviews/${pr}`)
            .then((data) => { applyReport(data); setLoading(false); })
            .catch(() => {});
        }
        pollTimerRef.current = setTimeout(() => pollJob(jobId), 1500);
      }
    } catch (e) {
      setPollingJobId(null);
      setJobPhase(null);
      setError(`Job polling failed: ${e.message}`);
      setLoading(false);
    }
  }, [repo, pr, fetchReport, fetchHistory, applyReport]);

  useEffect(() => {
    if (pollingJobId) {
      pollJob(pollingJobId);
    }
    return () => clearTimeout(pollTimerRef.current);
  }, [pollingJobId, pollJob]);

  const handleSubmit = (e) => {
    e.preventDefault();
    const parsed = parsePrInput(inputVal);
    if (parsed) {
      navigate(`/pr-review?repo=${parsed.repo}&pr=${parsed.pr}`);
    } else {
      setError("Invalid format. Use owner/repo#42 or full GitHub URL.");
    }
  };

  if (!repo || !pr) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface p-6 relative overflow-hidden">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-primary/5 rounded-full blur-[100px] pointer-events-none"></div>
        <div className="relative w-full max-w-[560px] p-10 rounded-3xl bg-surface-container-lowest/60 backdrop-blur-xl border border-outline-variant/40 shadow-2xl shadow-primary/10 flex flex-col items-center gap-6">
          <div className="w-20 h-20 rounded-full bg-primary/10 flex items-center justify-center border border-primary/20 shadow-inner">
            <span className="material-symbols-outlined text-primary text-[40px]">fact_check</span>
          </div>
          <div className="space-y-3 text-center">
            <h2 className="font-display-lg text-3xl text-on-surface font-bold tracking-tight">PR Review</h2>
            <p className="text-sm text-on-surface-variant leading-relaxed font-body">
              Analyze a pull request for structural risks, missing tests, and architectural changes.
            </p>
          </div>
          
          <form onSubmit={handleSubmit} className="w-full relative mt-4">
            <div className="flex items-center w-full rounded-md overflow-hidden border border-primary/50 bg-primary/5 focus-within:ring-2 focus-within:ring-primary/20">
              <div className="pl-4 pr-2 flex items-center text-primary/60">
                <span className="material-symbols-outlined text-[20px]">search</span>
              </div>
              <input
                type="text"
                value={inputVal}
                onChange={(e) => setInputVal(e.target.value)}
                className="flex-grow bg-transparent border-none py-4 px-2 focus:outline-none font-code text-[14px] text-on-surface placeholder:text-on-surface-variant/40"
                placeholder="owner/repo#42 or github.com/owner/repo/pull/42"
              />
              <button
                type="submit"
                disabled={!inputVal.trim()}
                className="px-6 py-4 bg-primary text-on-primary font-bold text-[14px] transition-all disabled:opacity-50 hover:bg-primary-container shrink-0"
              >
                Review
              </button>
            </div>
            {error && (
              <div className="absolute top-full mt-2 w-full text-center text-error text-[12px] font-code">
                {error}
              </div>
            )}
          </form>

          {/* repo's already-reviewed PRs (shown when arriving with ?repo=) */}
          {repo && history.length > 0 && (
            <div className="w-full mt-6 space-y-2">
              <p className="text-[10px] font-code font-bold uppercase tracking-widest text-on-surface-variant flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[14px]">history</span>
                Reviewed in {repo}
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {history.slice(0, 6).map((h) => (
                  <button
                    key={h.number}
                    onClick={() => navigate(`/pr-review?repo=${repo}&pr=${h.number}`)}
                    className="flex items-center justify-between p-2.5 rounded-lg bg-surface-container border border-outline-variant/40 hover:border-primary/50 hover:bg-surface-container-high transition-all group text-left"
                  >
                    <span className="font-code text-xs text-on-surface group-hover:text-primary transition-colors">#{h.number}</span>
                    <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-sm uppercase ${
                      h.level === "HIGH" ? "bg-red-500/20 text-red-400" :
                      h.level === "MEDIUM" ? "bg-orange-400/20 text-orange-400" : "bg-green-500/20 text-green-500"
                    }`}>{h.level}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  if ((loading || pollingJobId) && !report) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-primary border-t-transparent rounded-full motion-safe:animate-spin mx-auto"></div>
          <p className="font-code text-label text-on-surface-variant uppercase tracking-widest animate-pulse">
            {pollingJobId ? "Analyzing PR changes..." : "Loading report..."}
          </p>
          {pollingJobId && jobPhase && (
            <p className="font-code text-[10px] text-on-surface-variant/70 tracking-wide">{jobPhase}</p>
          )}
        </div>
      </div>
    );
  }

  if (tokenError) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface p-6">
        <div className="max-w-[28rem] w-full bg-surface border border-error p-8 text-center space-y-6 rounded-xl">
          <span className="material-symbols-outlined text-error text-[64px]">vpn_key_off</span>
          <div className="space-y-2">
            <h2 className="font-code text-heading-lg text-error font-bold">Access Denied</h2>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              The server requires a valid GITHUB_TOKEN to fetch and analyze pull requests. Please configure the token on the server.
            </p>
          </div>
          <button
            onClick={() => triggerAnalysis(repo, pr)}
            className="w-full bg-primary hover:bg-primary-container text-on-primary font-code font-bold py-3 rounded-lg transition-all active:scale-95"
          >
            RETRY
          </button>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface p-6">
        <div className="max-w-[28rem] w-full bg-surface border border-outline-variant p-8 text-center space-y-4 rounded-xl">
          <span className="material-symbols-outlined text-error text-[54px]">warning</span>
          <h2 className="font-code text-heading-lg text-error font-bold">Review Failed</h2>
          <p className="text-xs text-on-surface-variant leading-relaxed break-words">{error}</p>
          <div className="flex gap-3">
            <button
              onClick={() => triggerAnalysis(repo, pr)}
              className="flex-1 bg-primary hover:bg-primary-container text-on-primary font-code font-bold py-2 rounded-lg"
            >
              RETRY
            </button>
            <button
              onClick={() => navigate("/pr-review")}
              className="flex-1 border border-outline-variant hover:bg-surface-container-high font-code font-bold py-2 rounded-lg"
            >
              BACK
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!report) return null;

  // Breakdown bar setup
  const totalScore = report.risk_score || 0;
  let breakdownText = (report.breakdown || []).map(b => `${b.weight.toFixed(2)} ${b.signal}`).join(" + ");
  if (breakdownText) {
    breakdownText = `${breakdownText} = ${totalScore.toFixed(2)} → ${report.level}`;
  }

  // Risk severity uses FIXED semantic colors, deliberately independent of the
  // theme accent: HIGH rendered in blue (or in "jade green" when the user
  // picks that accent) reads as safe. Red = high, orange = medium, green = low.
  const riskBg = report.level === "HIGH" ? "bg-red-500"
                 : report.level === "MEDIUM" ? "bg-orange-400" : "bg-green-500";

  return (
    <div className="min-h-screen bg-background text-on-surface pb-12">
      <main className="pt-8 px-gutter max-w-container-max mx-auto space-y-8">

        {/* live analysis banner — page stays interactive while a job runs */}
        {(pollingJobId || jobError) && (
          <div className={`flex items-center gap-3 px-4 py-2.5 rounded-lg border font-code text-[11px] tracking-wider ${
            jobError ? "bg-red-900/20 border-red-700/40 text-red-400"
                     : "bg-primary/10 border-primary/30 text-primary"}`}>
            {jobError ? (
              <>
                <span className="material-symbols-outlined text-[16px]">error</span>
                <span>{jobError}</span>
              </>
            ) : (
              <>
                <div className="w-3.5 h-3.5 border-2 border-primary border-t-transparent rounded-full motion-safe:animate-spin shrink-0"></div>
                <span className="uppercase">Analyzing{jobPhase ? ` — ${jobPhase}` : "…"}</span>
              </>
            )}
          </div>
        )}

        {/* Header */}
        <section className="flex flex-col md:flex-row justify-between items-start gap-4">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <h1 className="font-display-lg text-3xl font-bold tracking-tight">
                {repo} <span className="text-primary">#{pr}</span>
              </h1>
              <span
                className={`px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider rounded-sm text-black ${riskBg}`}
                style={{ boxShadow: "0 0 14px color-mix(in srgb, currentColor 25%, transparent)" }}
              >
                {report.level} RISK
              </span>
            </div>
            <p className="font-code text-xs text-on-surface-variant uppercase tracking-widest flex items-center gap-2">
              <span className="material-symbols-outlined text-[14px]">calendar_today</span>
              Generated at {new Date(report.generated_at).toLocaleString()}
            </p>
          </div>
          <div className="flex gap-3">
            <button
              onClick={() => triggerAnalysis(repo, pr)}
              className="h-9 px-4 bg-surface-container hover:bg-surface-container-high border border-outline-variant font-code text-[11px] font-bold rounded-lg transition-all flex items-center gap-2"
            >
              <span className="material-symbols-outlined text-[16px]">refresh</span>
              RE-ANALYZE
            </button>
          </div>
        </section>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter items-start">
          
          <div className="lg:col-span-8 space-y-gutter">
            
            {/* Breakdown Card */}
            <div className="bg-surface-container border border-outline-variant p-6 rounded-xl space-y-4 glow-card">
              <h3 className="font-code text-sm font-bold uppercase text-on-surface-variant flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-[18px]">functions</span>
                Risk Score Computation
              </h3>
              
              <div className="space-y-2">
                {/* Horizontal Stacked Bar */}
                <div className="w-full h-6 bg-surface-container-highest rounded-sm flex overflow-hidden border border-outline-variant/20">
                  {report.breakdown && report.breakdown.length > 0 ? (
                    report.breakdown.map((b, idx) => {
                      // Alternate shades of primary for segments, or color by signal if preferred.
                      // We'll use opacity variants of the risk color.
                      const opacity = 100 - (idx * 20);
                      return (
                        <div 
                          key={idx} 
                          className={`h-full ${riskBg}`}
                          style={{ 
                            width: `${Math.max(5, (b.weight / totalScore) * 100)}%`,
                            opacity: opacity / 100 
                          }}
                          title={`${b.signal}: ${b.weight.toFixed(2)}`}
                        ></div>
                      );
                    })
                  ) : (
                    <div className={`h-full ${riskBg} w-full`} style={{ width: `${Math.min(totalScore * 100, 100)}%` }}></div>
                  )}
                </div>
                
                {/* Formula Text */}
                <div className="font-code text-[11px] bg-background border border-outline-variant/40 p-2.5 rounded-sm overflow-x-auto whitespace-nowrap text-on-surface/90">
                  {breakdownText || `Score = ${totalScore.toFixed(2)} → ${report.level}`}
                </div>
              </div>
            </div>

            {/* AI Change Summary — generated in the background after the
                deterministic checks; the card reflects that lifecycle */}
            {(report.summary || report.summary_pending) && (
              <div className="bg-surface-container border border-outline-variant p-6 rounded-xl space-y-3 glow-card">
                <h3 className="font-code text-sm font-bold uppercase text-on-surface-variant flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-[18px]">auto_awesome</span>
                  AI Change Summary
                </h3>
                {report.summary ? (
                  <p className="font-body text-[13px] leading-relaxed text-on-surface">{report.summary}</p>
                ) : pollingJobId ? (
                  <div className="flex items-center gap-3">
                    <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full motion-safe:animate-spin shrink-0"></div>
                    <p className="font-code text-[11px] uppercase tracking-wider text-on-surface-variant animate-pulse">
                      Generating in the background — the risk checks above are already final
                    </p>
                  </div>
                ) : (
                  <p className="font-code text-[11px] text-on-surface-variant">
                    Summary was not generated. Re-analyze to retry with the configured LLM.
                  </p>
                )}
              </div>
            )}

            {/* Quick Stats */}
            <div className="grid grid-cols-3 gap-gutter">
              <div className="bg-surface-container border border-outline-variant p-4 rounded-xl glow-card">
                <p className="font-code text-[10px] text-on-surface-variant uppercase mb-1">Files Changed</p>
                <p className="font-stat text-2xl font-bold">{report.files_changed || 0}</p>
              </div>
              <div className="bg-surface-container border border-outline-variant p-4 rounded-xl glow-card">
                <p className="font-code text-[10px] text-on-surface-variant uppercase mb-1">Lines Added</p>
                {/* red only past the large-change threshold — a 12-line PR isn't a warning */}
                <p className={`font-stat text-2xl font-bold ${(report.lines_added || 0) >= 400 ? "text-red-400" : "text-on-surface"}`}>
                  +{report.lines_added || 0}
                </p>
              </div>
              <div className="bg-surface-container border border-outline-variant p-4 rounded-xl glow-card">
                <p className="font-code text-[10px] text-on-surface-variant uppercase mb-1">Similarity</p>
                <p className="font-stat text-2xl font-bold text-primary">{(report.similarity * 100).toFixed(0)}%</p>
                <p className="font-code text-[9px] text-on-surface-variant uppercase">vs past bug-fix diffs</p>
              </div>
            </div>

            {/* Signals */}
            <div className="space-y-4">
              {report.warnings && report.warnings.length > 0 && (
                <div className="bg-orange-900/20 border border-orange-700/40 p-4 rounded-xl space-y-2">
                  <h4 className="font-code text-[11px] font-bold text-orange-400 uppercase flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-[16px]">warning</span> Warnings
                  </h4>
                  <ul className="space-y-1.5 pl-1">
                    {report.warnings.map((w, idx) => (
                      <li key={idx} className="font-body text-[13px] text-on-surface flex items-start gap-2">
                        <span className="text-orange-400 mt-1">•</span>
                        <span>{w}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {report.notes && report.notes.length > 0 && (
                <div className="bg-surface-container-high border border-outline-variant p-4 rounded-xl space-y-2">
                  <h4 className="font-code text-[11px] font-bold text-on-surface uppercase flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-[16px]">info</span> Notes
                  </h4>
                  <ul className="space-y-1.5 pl-1">
                    {report.notes.map((n, idx) => (
                      <li key={idx} className="font-body text-[13px] text-on-surface flex items-start gap-2">
                        <span className="text-on-surface-variant mt-1">•</span>
                        <span>{n}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {report.oks && report.oks.length > 0 && (
                <div className="bg-green-900/20 border border-green-700/30 p-4 rounded-xl space-y-2">
                  <h4 className="font-code text-[11px] font-bold text-green-500 uppercase flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-[16px]">check_circle</span> Oks
                  </h4>
                  <ul className="space-y-1.5 pl-1">
                    {report.oks.map((ok, idx) => (
                      <li key={idx} className="font-body text-[13px] text-on-surface flex items-start gap-2">
                        <span className="text-green-500 mt-1">•</span>
                        <span>{ok}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            
            {/* Markdown Report Toggle */}
            {report.markdown && (
              <div className="bg-surface-container border border-outline-variant rounded-xl overflow-hidden mt-6">
                <button
                  onClick={() => setShowMarkdown(!showMarkdown)}
                  className="w-full px-6 py-4 flex items-center justify-between hover:bg-surface-container-high transition-colors text-left"
                >
                  <span className="font-code text-sm font-bold uppercase text-on-surface-variant flex items-center gap-2">
                    <span className="material-symbols-outlined text-[18px]">article</span>
                    Full Markdown Report
                  </span>
                  <span className="material-symbols-outlined text-on-surface-variant">
                    {showMarkdown ? "expand_less" : "expand_more"}
                  </span>
                </button>
                {showMarkdown && (
                  <div className="p-6 border-t border-outline-variant bg-background">
                    <SimpleMarkdown text={report.markdown} />
                  </div>
                )}
              </div>
            )}
          </div>

          <aside className="lg:col-span-4 space-y-6">
            <div className="bg-surface-container border border-outline-variant p-5 rounded-xl">
              <h3 className="font-code text-[11px] font-bold uppercase tracking-wider text-on-surface-variant mb-4">
                Previously Reviewed PRs
              </h3>
              {history.length > 0 ? (
                <div className="space-y-2">
                  {history.map(h => (
                    <Link
                      key={h.number}
                      to={`/pr-review?repo=${repo}&pr=${h.number}`}
                      className={`block p-3 border rounded-lg transition-colors ${h.number.toString() === pr ? "bg-primary/10 border-primary text-primary font-bold" : "bg-surface-container border-outline-variant hover:border-primary/50 text-on-surface"}`}
                    >
                      <div className="flex justify-between items-center mb-1">
                        <span className="font-code text-sm">#{h.number}</span>
                        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-sm uppercase ${
                          h.level === "HIGH" ? "bg-red-500/20 text-red-400" :
                          h.level === "MEDIUM" ? "bg-orange-400/20 text-orange-400" : "bg-green-500/20 text-green-500"
                        }`}>
                          {h.level}
                        </span>
                      </div>
                      <div className="text-[10px] text-on-surface-variant font-code">
                        {new Date(h.generated_at).toLocaleDateString()}
                      </div>
                    </Link>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-on-surface-variant font-code p-4 text-center bg-surface-container border border-outline-variant/30 rounded-lg">
                  No other PRs reviewed for this repository yet.
                </p>
              )}
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
