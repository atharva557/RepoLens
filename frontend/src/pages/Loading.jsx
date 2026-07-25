import { useEffect, useState, useRef } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { getJSON, postJSON } from "../lib/api";
import { loadRepoSettings } from "../lib/settings";

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

  const pollIntervalRef = useRef(null);


  const handleRetry = async () => {
    setError(null);
    setJob(null);
    try {
      let res;
      if (username) {
        res = await postJSON(`/profiles/${username}`);
      } else if (nextTarget === "/hotspots" || nextTarget === "/dashboard") {
        const settings = loadRepoSettings(repo);
        res = await postJSON("/analyze", { repo, refresh: true, max_commits: settings.max_commits, top: settings.top });
      } else if (nextTarget === "/pr-review") {
        const pr = searchParams.get("pr");
        res = await postJSON(`/repos/${repo}/pr-reviews/${pr}`);
      } else {
        const settings = loadRepoSettings(repo);
        res = await postJSON("/commit-quality", { repo, max_commits: settings.max_commits, top: settings.top });
      }

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

    const poll = () => {
      getJSON(`/jobs/${jobId}`)
        .then((data) => {
          setJob(data);
          if (data.status === "done") {
            // Wait brief moment so the user sees 100%, then redirect
            clearInterval(pollIntervalRef.current);
            setTimeout(() => {
              const qs = new URLSearchParams(location.search);
              qs.delete("job");
              // Keep PR param if it exists, etc.
              navigate(`${nextTarget}?${qs.toString()}`);
            }, 800);
          } else if (data.status === "failed") {
            clearInterval(pollIntervalRef.current);
            setError(data.error || "Background task failed.");
          }
        })
        .catch((e) => {
          clearInterval(pollIntervalRef.current);
          // only a real 404 means the job record is gone; anything else
          // (network drop, 500) was being mislabelled as "server restarted"
          setError(e.status === 404
            ? `Job ${jobId} is no longer known to the server — it may have restarted. Retry to run it again.`
            : `Could not read job status: ${e.message}`);
        });
    };

    poll();
    pollIntervalRef.current = setInterval(poll, 1500);

    return () => {
      clearInterval(pollIntervalRef.current);
    };
  }, [jobId, repo, username, nextTarget, navigate, location.search, location.pathname]);

  const phase = job?.progress?.phase || "Initializing...";
  const detail = job?.progress?.detail || "";
  const pct = job?.progress?.pct;
  const isDone = job?.status === "done";
  const displayPct = isDone ? 100 : pct;

  return (
    <div className="min-h-[calc(100vh-52px)] bg-background text-on-surface flex flex-col justify-between overflow-hidden relative terminal-grid select-none">
      <div className="fixed bottom-10 right-10 z-0 pointer-events-none select-none opacity-[0.02]">
        <span className="font-stat text-[12rem] text-on-surface leading-none uppercase">
          ANALYZING
        </span>
      </div>

      <main className="flex-grow flex items-center justify-center pt-8 pb-12 px-gutter z-10">
        <div className="w-full max-w-[620px] space-y-6">
          <div className="bg-surface border border-outline-variant p-6 md:p-8 shadow-2xl">
            <div className="mb-6 space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-code text-label text-secondary uppercase tracking-wider">
                  {error ? "// PROCESS_FAILED" : "// PIPELINE_EXECUTION"}
                </span>
              </div>
              <h1 className="font-code text-heading-lg text-primary truncate max-w-full">
                {error ? "Analysis Failed" : phase}
              </h1>
              {!error && detail && (
                <p className="font-code text-[11px] text-on-surface-variant uppercase tracking-widest mt-1">
                  {detail}
                </p>
              )}
            </div>

            {error ? (
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
              <div className="space-y-6">
                <div>
                  <div className="flex justify-between items-end mb-2">
                    <span className="font-code text-label text-on-surface-variant">Task Sequence Progress</span>
                    <span className="font-stat text-heading-md text-primary font-bold">
                      {displayPct != null ? `${displayPct}%` : ""}
                    </span>
                  </div>
                  <div className="h-4 bg-surface-container-high border border-outline-variant relative overflow-hidden rounded-sm">
                    {displayPct != null ? (
                      <div
                        className="absolute top-0 left-0 h-full bg-primary transition-all duration-300 ease-out flex items-center justify-end"
                        style={{ width: `${displayPct}%` }}
                      >
                        <div className="absolute inset-0 animate-[shimmer_2s_infinite_linear] bg-gradient-to-r from-transparent via-white/10 to-transparent -translate-x-full"></div>
                      </div>
                    ) : (
                      <div className="absolute inset-0 bg-primary/20 animate-pulse"></div>
                    )}
                  </div>
                </div>

                <div className="pt-4 border-t border-outline-variant flex flex-col sm:flex-row justify-between items-center gap-3">
                  <div className="flex items-center gap-2"></div>
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
