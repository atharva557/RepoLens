import { useEffect, useState, useRef } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { getJSON, postJSON } from "../lib/api";

const LOG_LINES = [
  "[PROCESS] Scanned 124 author aliases...",
  "[COMPUTE] Generating temporal density matrix...",
  "[IO] Fetching blob data from tree: main...",
  "[AI] Tokenizing contribution deltas...",
  "[DATA] Indexing dependency graph nodes...",
  "[DB] Establishing document schema index...",
  "[QUALITY] Evaluating message semantic density...",
  "[HOTSPOTS] Ranking cyclomatic complexity vectors...",
];

export default function Loading() {
  const navigate = useNavigate();
  const location = useLocation();
  const searchParams = new URLSearchParams(location.search);
  const jobId = searchParams.get("job");
  const repo = searchParams.get("repo");
  const username = searchParams.get("user");
  const nextTarget = searchParams.get("next") || "/dashboard";

  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [progress, setProgress] = useState(15);
  const [logIndex, setLogIndex] = useState(0);
  const [secondsRemaining, setSecondsRemaining] = useState(45);

  const pollIntervalRef = useRef(null);
  const progressIntervalRef = useRef(null);
  const logIntervalRef = useRef(null);
  const countdownIntervalRef = useRef(null);

  // Parse path or url for display
  const displayTarget = repo || username || "Repository";

  const getStepStatus = (stepIndex) => {
    // 0: Meta, 1: History, 2: Activity split, 3: AI insights, 4: Health Report
    if (error || (job && job.status === "failed")) return "failed";
    if (!job) return "pending";

    const status = job.status;
    if (status === "done") return "complete";

    if (status === "pending") {
      if (stepIndex === 0) return "active";
      return "pending";
    }

    if (status === "running") {
      if (stepIndex < 2) return "complete";
      if (stepIndex === 2 || stepIndex === 3) return "active";
      return "pending";
    }

    return "pending";
  };

  const handleRetry = async () => {
    setError(null);
    setJob(null);
    setProgress(15);
    setSecondsRemaining(45);
    try {
      let res;
      if (username) {
        res = await postJSON(`/profiles/${username}`);
      } else if (nextTarget === "/hotspots" || nextTarget === "/dashboard") {
        res = await postJSON("/analyze", { repo, refresh: true });
      } else {
        res = await postJSON("/commit-quality", { repo });
      }

      // Update URL with new job id
      const newParams = new URLSearchParams(location.search);
      newParams.set("job", res.job_id);
      navigate(`${location.pathname}?${newParams.toString()}`, { replace: true });
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    if (!jobId) {
      setError("No job parameter found. Please return home and try again.");
      return;
    }

    // 1. Job Polling
    const poll = () => {
      getJSON(`/jobs/${jobId}`)
        .then((data) => {
          setJob(data);
          if (data.status === "done") {
            setProgress(100);
            clearInterval(pollIntervalRef.current);
            clearInterval(progressIntervalRef.current);
            clearInterval(countdownIntervalRef.current);
            
            // Wait brief moment so the user sees 100%, then redirect
            setTimeout(() => {
              const qs = new URLSearchParams();
              if (repo) qs.set("repo", repo);
              if (username) qs.set("user", username);
              navigate(`${nextTarget}?${qs.toString()}`);
            }, 800);
          } else if (data.status === "failed") {
            clearInterval(pollIntervalRef.current);
            clearInterval(progressIntervalRef.current);
            clearInterval(countdownIntervalRef.current);
            setError(data.error || "Background task failed.");
          }
        })
        .catch((e) => {
          // A 404 means the server restarted and forgot the job - treat as failed
          clearInterval(pollIntervalRef.current);
          clearInterval(progressIntervalRef.current);
          clearInterval(countdownIntervalRef.current);
          setError(`Job not found (404). The server might have restarted. Details: ${e.message}`);
        });
    };

    poll(); // immediate call
    pollIntervalRef.current = setInterval(poll, 1500);

    // 2. Progress animation (fake increment up to 92%)
    progressIntervalRef.current = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 92) return 92;
        const inc = Math.floor(Math.random() * 5) + 2; // +2..6%
        return Math.min(prev + inc, 92);
      });
    }, 1000);

    // 3. Log line rotation
    logIntervalRef.current = setInterval(() => {
      setLogIndex((prev) => (prev + 1) % LOG_LINES.length);
    }, 2000);

    // 4. Time remaining countdown
    countdownIntervalRef.current = setInterval(() => {
      setSecondsRemaining((prev) => (prev <= 5 ? 5 : prev - 1));
    }, 1000);

    return () => {
      clearInterval(pollIntervalRef.current);
      clearInterval(progressIntervalRef.current);
      clearInterval(logIntervalRef.current);
      clearInterval(countdownIntervalRef.current);
    };
  }, [jobId, repo, username, nextTarget, navigate, location.search, location.pathname]);

  const stepItems = [
    { label: "Repository metadata fetched", desc: "Source: GitHub API v3 · Success" },
    { label: "Commit history loaded", desc: "Full index cached successfully" },
    { label: "Analyzing contribution patterns...", desc: "Generating temporal density matrix" },
    { label: "Running AI insight generation", desc: "Invoking large language model agent" },
    { label: "Building system health report", desc: "Assembling final scoring layers" },
  ];

  return (
    <div className="min-h-[calc(100vh-52px)] bg-background text-on-surface flex flex-col justify-between overflow-hidden relative terminal-grid select-none">
      {/* Background decoration */}
      <div className="fixed bottom-10 right-10 z-0 pointer-events-none select-none opacity-[0.02]">
        <span className="font-stat text-[12rem] text-on-surface leading-none uppercase">
          ANALYZING
        </span>
      </div>

      <main className="flex-grow flex items-center justify-center pt-8 pb-12 px-gutter z-10">
        <div className="w-full max-w-[620px] space-y-6">
          <div className="bg-surface border border-outline-variant p-6 md:p-8 shadow-2xl">
            {/* Status Header */}
            <div className="mb-6 space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-code text-label text-secondary uppercase tracking-wider">
                  {error ? "// PROCESS_FAILED" : "// PIPELINE_EXECUTION"}
                </span>
              </div>
              <h1 className="font-code text-heading-lg text-primary truncate max-w-full">
                {error ? "Analysis Failed" : `Analyzing: ${displayTarget}`}
              </h1>
            </div>

            {error ? (
              // Error block
              <div className="space-y-6">
                <div className="p-4 bg-error-container/20 border border-error-container text-error rounded-sm font-code text-xs space-y-2">
                  <div className="flex items-center gap-2 font-bold text-[13px]">
                    <span className="material-symbols-outlined text-sm">warning</span>
                    <span>EXCEPTION RECORDED:</span>
                  </div>
                  <pre className="whitespace-pre-wrap leading-relaxed break-words font-code text-[11px] bg-black/40 p-3 border border-outline-variant/30 rounded-sm">
                    {error}
                  </pre>
                </div>

                <div className="flex flex-col sm:flex-row gap-3 pt-4 border-t border-outline-variant">
                  <button
                    onClick={handleRetry}
                    className="flex-1 bg-primary hover:bg-primary-container text-on-primary font-code font-bold py-2.5 px-4 transition-all rounded-sm flex items-center justify-center gap-2 active:scale-[0.98]"
                  >
                    <span className="material-symbols-outlined text-[18px]">refresh</span>
                    <span>RETRY_PROCESS</span>
                  </button>
                  <button
                    onClick={() => navigate("/")}
                    className="flex-1 border border-outline-variant hover:bg-surface-container-high font-code font-bold py-2.5 px-4 text-on-surface-variant transition-all rounded-sm flex items-center justify-center gap-2 active:scale-[0.98]"
                  >
                    <span className="material-symbols-outlined text-[18px]">home</span>
                    <span>RETURN_HOME</span>
                  </button>
                </div>
              </div>
            ) : (
              // Standard loading display
              <div className="space-y-6">
                {/* Progress bar */}
                <div>
                  <div className="flex justify-between items-end mb-2">
                    <span className="font-code text-label text-on-surface-variant">Task Sequence Progress</span>
                    <span className="font-stat text-heading-md text-primary font-bold">{progress}%</span>
                  </div>
                  <div className="h-4 bg-surface-container-high border border-outline-variant relative overflow-hidden rounded-sm">
                    <div
                      className="absolute top-0 left-0 h-full bg-primary transition-all duration-300 ease-out flex items-center justify-end"
                      style={{ width: `${progress}%` }}
                    >
                      {/* Shimmer Overlay */}
                      <div className="absolute inset-0 animate-[shimmer_2s_infinite_linear] bg-gradient-to-r from-transparent via-white/10 to-transparent -translate-x-full"></div>
                    </div>
                  </div>
                </div>

                {/* Steps checklist */}
                <div className="space-y-3 font-code text-xs">
                  {stepItems.map((step, idx) => {
                    const stepStatus = getStepStatus(idx);
                    
                    let icon = "radio_button_unchecked";
                    let iconColor = "text-on-surface-variant opacity-40";
                    let textClass = "text-on-surface opacity-40";
                    let contentBlock = null;

                    if (stepStatus === "complete") {
                      icon = "check_circle";
                      iconColor = "text-tertiary";
                      textClass = "text-on-surface";
                    } else if (stepStatus === "active") {
                      icon = "circle";
                      iconColor = "text-primary animate-pulse";
                      textClass = "text-primary font-bold";
                      
                      // Render terminal log simulator inside active step
                      contentBlock = (
                        <div className="mt-2 font-code text-[10px] text-primary/60 bg-surface-container-lowest p-2 border border-outline-variant/30 overflow-hidden select-none">
                          <div className="leading-relaxed">
                            {LOG_LINES[logIndex]}<br/>
                            {LOG_LINES[(logIndex + 1) % LOG_LINES.length]}
                          </div>
                        </div>
                      );
                    }

                    return (
                      <div key={idx} className="flex items-start gap-3">
                        <div className="mt-0.5 select-none">
                          <span className={`material-symbols-outlined text-[16px] ${iconColor}`} style={{ fontVariationSettings: stepStatus === "complete" ? "'FILL' 1" : "" }}>
                            {icon}
                          </span>
                        </div>
                        <div className="flex-1">
                          <p className={`text-[13px] ${textClass}`}>{step.label}</p>
                          {stepStatus !== "pending" && !contentBlock && (
                            <p className="text-[10px] text-on-surface-variant/50 mt-0.5">{step.desc}</p>
                          )}
                          {contentBlock}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Abort block */}
                <div className="pt-4 border-t border-outline-variant flex flex-col sm:flex-row justify-between items-center gap-3">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-on-surface-variant text-[16px]">schedule</span>
                    <span className="font-label text-label text-secondary uppercase tracking-wider">
                      Est. Remaining: ~{secondsRemaining}s
                    </span>
                  </div>
                  <button
                    onClick={() => navigate("/")}
                    className="font-code text-label text-error hover:bg-error/10 border border-transparent hover:border-error/20 px-3 py-1.5 transition-colors rounded-sm active:scale-95"
                  >
                    ABORT_PROCESS
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Terminal decals */}
          <div className="flex justify-between px-2 font-code text-[9px] text-on-surface-variant/40 uppercase tracking-widest">
            <span>Node: REPOLENS-JOB-ENGINE</span>
            <span>Uptime Check: OK</span>
            <span>Task ID: {jobId ? jobId.slice(0, 8) : "N/A"}</span>
          </div>
        </div>
      </main>
    </div>
  );
}
