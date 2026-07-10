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
    <div
      className="min-h-[calc(100vh-52px)] flex flex-col justify-between"
      style={{ backgroundColor: "#141414" }}
    >
      <main className="flex-grow flex flex-col items-center pt-[80px] pb-[80px] px-4 w-full">

        {/* ── Hero ── */}
        <div className="text-center flex flex-col items-center w-full">
          <h1
            style={{
              color: "#D4855A",
              fontSize: "72px",
              fontWeight: "bold",
              letterSpacing: "-1px",
              lineHeight: 1,
            }}
          >
            RepoLens
          </h1>
          <p
            style={{
              color: "rgba(255,255,255,0.55)",
              fontSize: "16px",
              maxWidth: "480px",
              margin: "24px auto 0",
              lineHeight: 1.75,
            }}
          >
            Analyze repositories instantly. Understand codebases, find
            hotspots, and evaluate commit quality at a glance.
          </p>
        </div>

        {/* ── Repository Input Spotlight ── */}
        <div className="mt-[64px] w-full max-w-[640px] flex flex-col items-center">

          {/* Decorative label row — gradient lines + icon + all-caps label */}
          <div className="flex items-center w-full mb-[16px]">
            <div
              className="flex-grow h-[1px]"
              style={{
                background:
                  "linear-gradient(to right, transparent, rgba(212,133,90,0.55))",
              }}
            />
            <div
              className="flex items-center gap-[8px] px-[14px]"
              style={{ color: "#D4855A", flexShrink: 0 }}
            >
              <span
                style={{
                  fontSize: "11px",
                  textTransform: "uppercase",
                  letterSpacing: "0.16em",
                  fontWeight: "bold",
                  whiteSpace: "nowrap",
                }}
              >
                Enter GitHub Repository Link
              </span>
            </div>
            <div
              className="flex-grow h-[1px]"
              style={{
                background:
                  "linear-gradient(to left, transparent, rgba(212,133,90,0.55))",
              }}
            />
          </div>

          {/* Input form */}
          <form onSubmit={handleFormSubmit} className="w-full relative">
            <div
              className="flex items-center w-full rounded-[4px] overflow-hidden transition-shadow"
              style={{
                border: "1.5px solid rgba(212,133,90,0.75)",
                backgroundColor: "rgba(212,133,90,0.04)",
                boxShadow: "0 0 20px rgba(212,133,90,0.12)",
              }}
            >
              <div
                className="pl-[16px] pr-[8px] flex items-center"
                style={{ color: "rgba(255,255,255,0.3)" }}
              >
                <span className="material-symbols-outlined text-[20px]">
                  content_paste
                </span>
              </div>

              <input
                type="text"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                disabled={submitting}
                className="flex-grow bg-transparent border-none py-[16px] px-[8px] focus:outline-none focus:ring-0 placeholder:text-[rgba(255,255,255,0.28)]"
                style={{
                  color: "rgba(255,255,255,0.85)",
                  fontFamily: "monospace",
                  fontSize: "14px",
                }}
                placeholder="https://github.com/owner/repository"
              />

              <button
                type="submit"
                disabled={submitting || !url.trim()}
                className="px-[24px] py-[16px] flex items-center gap-[8px] transition-all disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90"
                style={{
                  backgroundColor: "#D4855A",
                  color: "#141414",
                  fontWeight: "bold",
                  fontSize: "14px",
                  flexShrink: 0,
                }}
              >
                <span>{submitting ? "Analyzing..." : "Analyze"}</span>
                <span className="material-symbols-outlined text-[16px]">
                  arrow_forward
                </span>
              </button>
            </div>

            {error && (
              <div className="absolute top-full mt-[8px] w-full text-center text-red-400 text-[12px]">
                {error}
              </div>
            )}
          </form>
        </div>

        {/* ── Recent Analysis ── */}
        <div className="mt-[64px] w-full max-w-[640px] flex flex-col items-center">

          {/* Section heading — faint gradient lines + amber dots + amber title */}
          <div className="flex items-center w-full mb-[24px]">
            <div
              className="flex-grow h-[1px]"
              style={{
                background:
                  "linear-gradient(to right, transparent, rgba(212,133,90,0.3))",
              }}
            />
            <div
              className="w-[5px] h-[5px] rounded-full mx-[12px] flex-shrink-0"
              style={{ backgroundColor: "#D4855A" }}
            />
            <h2
              style={{
                color: "#D4855A",
                fontSize: "16px",
                fontWeight: "bold",
                whiteSpace: "nowrap",
              }}
            >
              Recent Analysis
            </h2>
            <div
              className="w-[5px] h-[5px] rounded-full mx-[12px] flex-shrink-0"
              style={{ backgroundColor: "#D4855A" }}
            />
            <div
              className="flex-grow h-[1px]"
              style={{
                background:
                  "linear-gradient(to left, transparent, rgba(212,133,90,0.3))",
              }}
            />
          </div>

          {/* Repo list */}
          <div
            className="w-full relative overflow-hidden"
            style={{
              border: "1px solid rgba(255,255,255,0.07)",
              borderRadius: "8px",
              backgroundColor: "transparent",
            }}
          >
            {repos.length === 0 ? (
              <div
                className="p-[32px] text-center"
                style={{ color: "rgba(255,255,255,0.35)", fontSize: "14px" }}
              >
                No repositories analyzed yet.
              </div>
            ) : (
              <div
                className="flex flex-col w-full overflow-y-auto"
                style={{
                  maxHeight: "228px",
                  scrollbarWidth: "none",
                  msOverflowStyle: "none",
                }}
              >
                <style>{`
                  .hide-scroll::-webkit-scrollbar { display: none; }
                `}</style>
                <div className="flex flex-col w-full hide-scroll">
                  {repos.map((r, i) => {
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
                        className="flex items-center justify-between p-[16px] cursor-pointer hover:bg-white/5 transition-colors flex-shrink-0"
                        style={{
                          borderBottom:
                            i !== repos.length - 1
                              ? "1px solid rgba(255,255,255,0.06)"
                              : "none",
                          height: "76px",
                        }}
                      >
                        <div className="flex flex-col gap-[4px]">
                          <span
                            style={{
                              color: "rgba(255,255,255,0.85)",
                              fontFamily: "monospace",
                              fontWeight: "bold",
                              fontSize: "14px",
                            }}
                          >
                            {r.repo}
                          </span>
                          <div className="flex items-center gap-[8px]">
                            <span
                              style={{
                                color: "rgba(255,255,255,0.35)",
                                fontSize: "12px",
                              }}
                            >
                              {r.commits} commits
                            </span>
                            {(r.hotspots || r.commit_quality) && (
                              <div className="flex items-center gap-[8px]">
                                {r.hotspots && (
                                  <span
                                    style={{
                                      color: "#D4855A",
                                      fontSize: "12px",
                                    }}
                                  >
                                    • hotspots
                                  </span>
                                )}
                                {r.commit_quality && (
                                  <span
                                    style={{
                                      color: "#D4855A",
                                      fontSize: "12px",
                                    }}
                                  >
                                    • quality
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        </div>

                        <div className="flex flex-col items-end gap-[4px]">
                          <span
                            style={{
                              color: "rgba(255,255,255,0.3)",
                              fontSize: "11px",
                            }}
                          >
                            {lastActive ? timeAgo(lastActive) : "analyzed"}
                          </span>
                          <span
                            className="material-symbols-outlined"
                            style={{
                              color: "rgba(255,255,255,0.3)",
                              fontSize: "16px",
                            }}
                          >
                            arrow_forward
                          </span>
                        </div>
                      </a>
                    );
                  })}
                </div>
              </div>
            )}

            {repos.length > 3 && (
              <div
                className="absolute bottom-0 left-0 w-full h-[48px] pointer-events-none"
                style={{
                  background:
                    "linear-gradient(to bottom, transparent, #141414)",
                  borderBottomLeftRadius: "8px",
                  borderBottomRightRadius: "8px",
                }}
              />
            )}
          </div>
        </div>
      </main>

      {/* ── Footer (unchanged) ── */}
      <footer
        className="h-[40px] border-t border-outline-variant flex items-center px-4 overflow-hidden"
        style={{
          backgroundColor: "#141414",
          borderColor: "rgba(255,255,255,0.07)",
        }}
      >
        <div
          className="max-w-[640px] mx-auto w-full flex justify-between font-code text-[10px] uppercase tracking-tighter"
          style={{ color: "rgba(255,255,255,0.35)" }}
        >
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1.5">
              <span
                className={`w-2 h-2 rounded-full ${health?.status === "ok"
                  ? "bg-green-500 animate-pulse"
                  : "bg-red-500"
                  }`}
              />
              {health?.status === "ok" ? "SYSTEM_READY" : "SYSTEM_OFFLINE"}
            </span>
            <span className="hidden sm:inline">
              STORE: {health?.store || "LOCAL_JSON"}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <span className="hidden md:inline">
              API VERSION: {health?.version || "0.4"}
            </span>
            <span>Uptime: 99.99%</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
