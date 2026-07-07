import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getJSON, postJSON } from "../lib/api";

function getRepoKey(repoUrl) {
  let cleaned = repoUrl.trim();
  if (cleaned.includes("github.com/")) {
    const parts = cleaned.split("github.com/");
    if (parts.length > 1) {
      const pathParts = parts[1].split("/");
      if (pathParts.length >= 2) {
        return `${pathParts[0]}/${pathParts[1]}`.replace(/\.git$/, "");
      }
    }
  }
  return cleaned;
}

function timeAgo(dateString) {
  if (!dateString) return "unknown";
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now - date;
  if (isNaN(diffMs)) return "some time ago";
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function Home() {
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [repos, setRepos] = useState([]);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    Promise.all([
      getJSON("/repos").catch(() => ({ repos: [] })),
      getJSON("/health").catch(() => null),
    ])
      .then(([reposData, healthData]) => {
        setRepos(reposData.repos || []);
        setHealth(healthData);
        setLoading(false);
      })
      .catch((e) => {
        setError(String(e));
        setLoading(false);
      });
  }, []);

  const handleAnalyze = async (targetRepo) => {
    if (!targetRepo) return;
    setSubmitting(true);
    setError(null);
    try {
      const repoKey = getRepoKey(targetRepo);
      const res = await postJSON("/analyze", {
        repo: targetRepo,
        refresh: false,
        top: 15,
      });
      // Navigate to loading page
      navigate(`/loading?job=${res.job_id}&repo=${repoKey}&next=/dashboard`);
    } catch (e) {
      setError(String(e));
      setSubmitting(false);
    }
  };

  const handleFormSubmit = (e) => {
    e.preventDefault();
    handleAnalyze(url);
  };

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-[#0e0e0e] text-on-surface">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto"></div>
          <p className="font-code text-label text-on-surface-variant uppercase tracking-widest animate-pulse">
            Booting system interface...
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-52px)] bg-background text-on-surface flex flex-col justify-between">
      <main className="flex-grow flex flex-col items-center px-gutter pt-16 pb-16">
        <div className="w-full max-w-[760px] space-y-16">
          
          {/* Input Section */}
          <div className="w-full">
            <form onSubmit={handleFormSubmit} className="relative group">
              <div className="absolute -inset-1 bg-primary/10 blur opacity-0 group-focus-within:opacity-100 transition duration-500 rounded-sm"></div>
              <div className="relative flex items-center bg-surface-container-lowest border border-outline-variant rounded-sm overflow-hidden focus-within:border-primary transition-colors">
                <div className="pl-4 pr-3 text-on-surface-variant flex items-center">
                  <span className="material-symbols-outlined text-[20px]">content_paste</span>
                </div>
                <input
                  type="text"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  disabled={submitting}
                  className="w-full bg-transparent border-none text-on-surface font-code text-[14px] py-4 focus:ring-0 focus:outline-none placeholder:text-surface-container-highest placeholder:opacity-50"
                  placeholder="https://github.com/owner/repository or local path"
                />
                <button
                  type="submit"
                  disabled={submitting || !url.trim()}
                  className="bg-primary hover:bg-primary-container text-on-primary font-bold text-[14px] px-8 py-4 flex items-center gap-2 transition-all active:scale-[0.98] whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span>{submitting ? "Analyzing..." : "Analyze"}</span>
                  <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                </button>
              </div>
            </form>

            {error && (
              <div className="mt-4 p-3 bg-error-container/20 border border-error-container/50 text-error rounded-sm font-code text-xs flex items-start gap-2 shadow-sm">
                <span className="material-symbols-outlined text-sm mt-0.5">error</span>
                <span>{error}</span>
              </div>
            )}
          </div>

          {/* Recent Analysis Centered Section */}
          <div className="flex flex-col items-center w-full">
            {/* Section Header */}
            <div className="flex items-center w-full justify-center mb-6 opacity-90">
              <div className="h-[1px] w-full max-w-[140px] bg-primary/40"></div>
              <div className="w-1.5 h-1.5 rounded-full bg-primary/80 mx-3 shadow-[0_0_8px_var(--color-primary)]"></div>
              <h2 className="font-display text-[18px] md:text-[20px] text-primary font-semibold tracking-wide whitespace-nowrap px-2">Recent Analysis</h2>
              <div className="w-1.5 h-1.5 rounded-full bg-primary/80 mx-3 shadow-[0_0_8px_var(--color-primary)]"></div>
              <div className="h-[1px] w-full max-w-[140px] bg-primary/40"></div>
            </div>

            {/* Cards Container */}
            <div className="w-full">
              {repos.length === 0 ? (
                <div className="p-10 bg-surface-container-lowest border border-outline-variant/50 rounded-lg text-center">
                  <span className="material-symbols-outlined text-[48px] text-surface-container-highest mb-4 block">history</span>
                  <p className="text-on-surface-variant font-code text-sm">No repositories analyzed yet.</p>
                </div>
              ) : (
                <div className="w-full bg-surface-container-lowest/30 backdrop-blur-sm border border-outline-variant/40 rounded-lg overflow-hidden flex flex-col divide-y divide-outline-variant/40 max-h-[500px] overflow-y-auto scrollbar-thin">
                  {repos.map((r) => {
                    const hotspotTime = r.hotspots?.generated_at || null;
                    const qualityTime = r.commit_quality?.generated_at || null;
                    const lastActive = hotspotTime || qualityTime;

                    return (
                      <a
                        key={r.repo}
                        href={`/dashboard?repo=${r.repo}`}
                        onClick={(e) => {
                          e.preventDefault();
                          navigate(`/dashboard?repo=${r.repo}`);
                        }}
                        className="group flex flex-col sm:flex-row sm:items-center justify-between p-4 sm:p-5 hover:bg-surface-container-high transition-colors duration-200 cursor-pointer"
                      >
                        <div className="flex flex-col gap-1.5">
                          <span className="font-code text-[15px] text-on-surface font-semibold tracking-tight group-hover:text-primary transition-colors">
                            {r.repo}
                          </span>
                          <div className="flex flex-wrap items-center gap-2 text-[12px] text-on-surface-variant font-code">
                            <span>{r.commits} commits</span>
                            {(r.hotspots || r.commit_quality) && (
                              <div className="flex items-center gap-2">
                                {r.hotspots && <span className="flex items-center gap-1.5 text-primary/80"><span className="w-1 h-1 rounded-full bg-primary/80"></span>hotspots</span>}
                                {r.commit_quality && <span className="flex items-center gap-1.5 text-tertiary/80"><span className="w-1 h-1 rounded-full bg-tertiary/80"></span>quality</span>}
                              </div>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center justify-between sm:justify-end gap-5 mt-4 sm:mt-0">
                          <span className="font-code text-[12px] text-on-surface-variant/80">
                            {lastActive ? timeAgo(lastActive) : "analyzed"}
                          </span>
                          <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary transition-colors duration-200 text-[20px]">
                            arrow_forward
                          </span>
                        </div>
                      </a>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="h-[40px] border-t border-outline-variant bg-surface flex items-center px-gutter overflow-hidden">
        <div className="max-w-container-max mx-auto w-full flex justify-between font-code text-[10px] text-on-surface-variant uppercase tracking-tighter">
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${health?.status === "ok" ? "bg-green-500 animate-pulse" : "bg-red-500"}`}></span>
              {health?.status === "ok" ? "SYSTEM_READY" : "SYSTEM_OFFLINE"}
            </span>
            <span className="hidden sm:inline">
              STORE: {health?.store || "LOCAL_JSON"}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <span className="hidden md:inline">API VERSION: {health?.version || "0.4"}</span>
            <span>Uptime: 99.99%</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
