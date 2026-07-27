import { useEffect, useState, useRef, useContext } from "react";
import { useNavigate } from "react-router-dom";
import { getJSON, postJSON } from "../lib/api";
import { loadRepoSettings, saveRepoSettings } from "../lib/settings";
import { ThemeContext } from "../lib/theme";
import SyncBadge from "../components/SyncBadge";

// full GitHub URL or bare owner/repo shorthand (the backend accepts both)
function looksLikeRepo(text) {
  const t = (text || "").trim();
  return /github\.com\/[\w.-]+\/[\w.-]+/.test(t) || /^[\w.-]+\/[\w.-]+$/.test(t);
}

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


export default function Home() {
  const navigate = useNavigate();
  const { settings: globalSettings } = useContext(ThemeContext);
  const [url, setUrl] = useState("");
  const [repos, setRepos] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [maxCommits, setMaxCommits] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const inputRef = useRef(null);

  const resolvedTheme = globalSettings.theme === "system"
    ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : globalSettings.theme;
  const isLight = resolvedTheme === "light";

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "/" && e.target.tagName !== "INPUT" && e.target.tagName !== "TEXTAREA") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    // the API lists repos alphabetically; "Recent Analysis" must mean it
    const analyzedAt = (r) =>
      r.hotspots?.generated_at || r.commit_quality?.generated_at || "";
    const load = () => {
      // 30s TTL absorbs the focus/visibility re-loads below; analysis
      // triggers clear the client cache, so fresh results still show
      Promise.all([
        getJSON("/repos", { ttl: 30000 }).catch(() => ({ repos: [] })),
        getJSON("/profiles", { ttl: 30000 }).catch(() => ({ profiles: [] })),
        getJSON("/health", { ttl: 30000 }).catch(() => null),
      ])
        .then(([reposData, profilesData, healthData]) => {
          const sorted = [...(reposData.repos || [])].sort((a, b) =>
            analyzedAt(b).localeCompare(analyzedAt(a))
          );
          setRepos(sorted);
          setProfiles(profilesData.profiles || []);
          setHealth(healthData);
          setLoading(false);
        })
        .catch((e) => {
          setError(String(e));
          setLoading(false);
        });
    };
    load();
    // coming back from /loading or another tab must show the fresh analysis
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, []);

  const handleAnalyze = async (targetRepo) => {
    if (!targetRepo) return;
    setSubmitting(true);
    setError(null);
    try {
      const repoKey = getRepoKey(targetRepo);
      const settings = loadRepoSettings(repoKey);

      if (maxCommits) {
        const parsedMax = parseInt(maxCommits, 10);
        settings.max_commits = isNaN(parsedMax) ? undefined : parsedMax;
        saveRepoSettings(repoKey, settings);
      }

      const res = await postJSON("/analyze", {
        repo: targetRepo,
        refresh: false,
        max_commits: settings.max_commits,
        top: settings.top,
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
      <div className="min-h-[calc(100vh-52px)] flex items-center justify-center bg-background text-on-surface">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-primary border-t-transparent rounded-full motion-safe:animate-spin mx-auto"></div>
          <p className="font-code text-label text-on-surface-variant uppercase tracking-widest animate-pulse">
            Booting system interface...
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-52px)] flex flex-col justify-between bg-background">
      <main className="flex-grow flex flex-col items-center pt-[80px] pb-[80px] px-4 w-full">

        {/* ── Hero ── */}
        <div className="text-center flex flex-col items-center w-full">
          <h1
            className="text-primary glow-text text-5xl md:text-[72px]"
            style={{
              fontWeight: "bold",
              letterSpacing: "-1px",
              lineHeight: 1,
            }}
          >
            RepoLens
          </h1>
          <p
            className="text-on-surface-variant text-sm md:text-base"
            style={{
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
                  "linear-gradient(to right, transparent, color-mix(in srgb, var(--color-primary) 55%, transparent))",
              }}
            />
            <div
              className="flex items-center gap-[8px] px-[14px] text-primary"
              style={{ flexShrink: 0 }}
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
                  "linear-gradient(to left, transparent, color-mix(in srgb, var(--color-primary) 55%, transparent))",
              }}
            />
          </div>

          {/* Input form */}
          <form onSubmit={handleFormSubmit} className="w-full relative">
            <div
              className="flex items-center w-full rounded-[4px] overflow-hidden transition-shadow"
              style={{
                border: "1.5px solid color-mix(in srgb, var(--color-primary) 75%, transparent)",
                backgroundColor: "color-mix(in srgb, var(--color-primary) 5%, transparent)",
                boxShadow: isLight ? "0 4px 12px rgba(0,0,0,0.05)" : "0 0 20px color-mix(in srgb, var(--color-primary) 14%, transparent)",
              }}
            >
              <div className="pl-[16px] pr-[8px] flex items-center text-on-surface-variant/50">
                <span className="material-symbols-outlined text-[20px]">
                  content_paste
                </span>
              </div>

              <input
                ref={inputRef}
                type="text"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onPaste={(e) => {
                  // settings drawer: "Auto-analyze on paste"
                  if (!globalSettings?.autoAnalyze || submitting) return;
                  const pasted = e.clipboardData.getData("text").trim();
                  if (looksLikeRepo(pasted)) {
                    e.preventDefault();
                    setUrl(pasted);
                    handleAnalyze(pasted);
                  }
                }}
                disabled={submitting}
                aria-label="GitHub Repository URL"
                className="flex-grow bg-transparent border-none py-[16px] px-[8px] focus:outline-none focus:ring-0 text-on-surface placeholder:text-on-surface-variant/40"
                style={{
                  fontFamily: "monospace",
                  fontSize: "14px",
                }}
                placeholder="https://github.com/owner/repository"
              />

              <button
                type="submit"
                disabled={submitting || !url.trim()}
                aria-label="Analyze Repository"
                className={`px-4 md:px-[24px] py-[16px] flex items-center gap-[8px] transition-all disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 active:scale-95 bg-primary text-on-primary ${isLight ? "" : "glow-primary"}`}
                style={{
                  fontWeight: "bold",
                  fontSize: "14px",
                  flexShrink: 0,
                }}
              >
                <span className="hidden sm:inline">{submitting ? "Analyzing..." : "Analyze"}</span>
                <span className="sm:hidden">{submitting ? "..." : "Go"}</span>
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

          {/* Advanced toggle */}
          <div className="w-full mt-4 flex flex-col items-end">
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="text-[11px] text-on-surface-variant/60 hover:text-primary font-bold uppercase tracking-wider flex items-center gap-1 transition-colors"
            >
              <span className="material-symbols-outlined text-[14px]">settings</span>
              Advanced Options
            </button>
            {showAdvanced && (
              <div className="mt-2 w-full flex justify-end">
                <div className="flex items-center gap-3 bg-primary/5 border border-primary/30 rounded p-2">
                  <label className="text-[11px] text-on-surface-variant/70 uppercase tracking-wider font-bold">Max Commits:</label>
                  <input
                    type="number"
                    value={maxCommits}
                    onChange={(e) => setMaxCommits(e.target.value)}
                    disabled={submitting}
                    placeholder="Full history"
                    className="bg-surface-container-high border border-primary/30 rounded px-2 py-1 text-sm text-on-surface w-32 focus:outline-none focus:border-primary"
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ── Profiles Rail ── */}
        <div className="mt-[64px] w-full max-w-[640px] flex flex-col items-center">
          <div className="flex items-center w-full mb-[24px]">
            <div
              className="flex-grow h-[1px]"
              style={{
                background: "linear-gradient(to right, transparent, color-mix(in srgb, var(--color-primary) 30%, transparent))",
              }}
            />
            <div
              className="w-[5px] h-[5px] rounded-full mx-[12px] flex-shrink-0"
              style={{ backgroundColor: "var(--color-primary)" }}
            />
            <h2
              style={{
                color: "var(--color-primary)",
                fontSize: "16px",
                fontWeight: "bold",
                whiteSpace: "nowrap",
              }}
            >
              Developer Profiles
            </h2>
            <div
              className="w-[5px] h-[5px] rounded-full mx-[12px] flex-shrink-0"
              style={{ backgroundColor: "var(--color-primary)" }}
            />
            <div
              className="flex-grow h-[1px]"
              style={{
                background: "linear-gradient(to left, transparent, color-mix(in srgb, var(--color-primary) 30%, transparent))",
              }}
            />
          </div>

          <div
            className="w-full relative overflow-x-auto overflow-y-hidden"
            style={{ scrollbarWidth: "none", msOverflowStyle: "none" }}
          >
            <style>{`
              .hide-scroll::-webkit-scrollbar { display: none; }
            `}</style>

            {profiles.length === 0 ? (
              <div
                className="w-full p-[32px] text-center border border-outline-variant/30 rounded-[8px]"
                style={{ color: "rgba(255,255,255,0.35)", fontSize: "14px" }}
              >
                No profiles built yet — analyze a developer above.
              </div>
            ) : (
              <div className="flex gap-4 hide-scroll px-1 pb-4">
                {profiles.map(p => (
                  <div
                    key={p.username}
                    onClick={() => navigate(`/profile?user=${p.username}`)}
                    className="flex flex-col items-center gap-3 p-4 border border-outline-variant/30 rounded-[8px] bg-[rgba(255,255,255,0.02)] hover:bg-[rgba(255,255,255,0.05)] cursor-pointer transition-colors min-w-[140px] shrink-0"
                  >
                    <div className="w-14 h-14 rounded-full bg-primary/20 flex items-center justify-center border border-primary/30 overflow-hidden">
                      {p.avatar_url ? (
                        <img src={p.avatar_url} alt={p.username} className="w-full h-full object-cover" />
                      ) : (
                        <span className="font-display-lg text-lg text-primary font-bold">
                          {p.username.slice(0, 2).toUpperCase()}
                        </span>
                      )}
                    </div>
                    <div className="flex flex-col items-center">
                      <span className="font-code font-bold text-[13px] text-on-surface truncate max-w-[120px]">
                        @{p.username}
                      </span>
                      <span className="font-code text-[9px] text-primary uppercase mt-1 px-1.5 py-0.5 border border-primary/30 bg-primary/10 rounded-sm">
                        {p.primary_type || "Contributor"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Recent Analysis ── */}
        <div className="mt-[64px] w-full max-w-[640px] flex flex-col items-center">

          {/* Section heading — faint gradient lines + amber dots + amber title */}
          <div className="flex items-center w-full mb-[24px]">
            <div
              className="flex-grow h-[1px]"
              style={{
                background:
                  "linear-gradient(to right, transparent, color-mix(in srgb, var(--color-primary) 30%, transparent))",
              }}
            />
            <div
              className="w-[5px] h-[5px] rounded-full mx-[12px] flex-shrink-0"
              style={{ backgroundColor: "var(--color-primary)" }}
            />
            <h2
              style={{
                color: "var(--color-primary)",
                fontSize: "16px",
                fontWeight: "bold",
                whiteSpace: "nowrap",
              }}
            >
              Recent Analysis
            </h2>
            <div
              className="w-[5px] h-[5px] rounded-full mx-[12px] flex-shrink-0"
              style={{ backgroundColor: "var(--color-primary)" }}
            />
            <div
              className="flex-grow h-[1px]"
              style={{
                background:
                  "linear-gradient(to left, transparent, color-mix(in srgb, var(--color-primary) 30%, transparent))",
              }}
            />
          </div>

          {/* Repo list */}
          <div
            className={`w-full relative ${isLight ? "" : "overflow-hidden"}`}
            style={
              isLight
                ? {}
                : {
                  border: "1px solid rgba(255,255,255,0.07)",
                  borderRadius: "8px",
                  backgroundColor: "transparent",
                }
            }
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
                className={`flex flex-col w-full overflow-y-auto ${isLight ? "space-y-3 p-1" : ""}`}
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
                        className={`flex items-center justify-between cursor-pointer transition-colors flex-shrink-0 ${isLight
                            ? "bg-surface-container border border-outline-variant/40 shadow-sm rounded-lg p-[16px] hover:border-outline-variant"
                            : "p-[16px] hover:bg-white/5"
                          }`}
                        style={
                          isLight
                            ? { height: "76px" }
                            : {
                              borderBottom: i !== repos.length - 1 ? "1px solid rgba(255,255,255,0.06)" : "none",
                              height: "76px",
                            }
                        }
                      >
                        <div className="flex flex-col gap-[4px]">
                          <span
                            className={isLight ? "font-code font-bold text-[14px] text-on-surface" : ""}
                            style={
                              isLight
                                ? {}
                                : {
                                  color: "rgba(255,255,255,0.85)",
                                  fontFamily: "monospace",
                                  fontWeight: "bold",
                                  fontSize: "14px",
                                }
                            }
                          >
                            {r.repo}
                          </span>
                          <div className="flex items-center gap-[8px]">
                            <span
                              className={isLight ? "text-[12px] text-on-surface-variant font-medium" : ""}
                              style={
                                isLight
                                  ? {}
                                  : {
                                    color: "rgba(255,255,255,0.35)",
                                    fontSize: "12px",
                                  }
                              }
                            >
                              {r.commits} commits
                            </span>
                            {(r.hotspots || r.commit_quality) && (
                              <div className="flex items-center gap-[8px]">
                                {r.hotspots && (
                                  <span
                                    className={isLight ? "text-[12px] text-primary font-bold" : ""}
                                    style={
                                      isLight
                                        ? {}
                                        : {
                                          color: "var(--color-primary)",
                                          fontSize: "12px",
                                        }
                                    }
                                  >
                                    • hotspots
                                  </span>
                                )}
                                {r.commit_quality && (
                                  <span
                                    className={isLight ? "text-[12px] text-primary font-bold" : ""}
                                    style={
                                      isLight
                                        ? {}
                                        : {
                                          color: "var(--color-primary)",
                                          fontSize: "12px",
                                        }
                                    }
                                  >
                                    • quality
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                          {r.pr_reviews && r.pr_reviews.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1.5">
                              {r.pr_reviews.map((prNum) => (
                                <button
                                  key={prNum}
                                  onClick={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    navigate(`/pr-review?repo=${r.repo}&pr=${prNum}`);
                                  }}
                                  className={
                                    isLight
                                      ? "px-1.5 py-0.5 bg-primary/10 hover:bg-primary/20 text-primary border border-primary/50 rounded text-[9px] font-bold font-code transition-colors"
                                      : "px-1.5 py-0.5 bg-primary/10 hover:bg-primary/20 text-primary border border-primary/30 rounded text-[9px] font-bold font-code transition-colors"
                                  }
                                >
                                  #{prNum}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>

                        <div className="flex flex-col items-end gap-[4px]">
                          {lastActive && <SyncBadge timestamp={lastActive} />}
                          <span
                            className={
                              isLight
                                ? "material-symbols-outlined text-[16px] text-on-surface-variant/50"
                                : "material-symbols-outlined"
                            }
                            style={
                              isLight
                                ? {}
                                : {
                                  color: "rgba(255,255,255,0.3)",
                                  fontSize: "16px",
                                }
                            }
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

            {!isLight && repos.length > 3 && (
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
          className="max-w-[640px] mx-auto w-full flex flex-col sm:flex-row justify-between font-code text-[10px] uppercase tracking-tighter gap-2 sm:gap-0"
          style={{ color: "rgba(255,255,255,0.35)" }}
        >
          <div className="flex items-center gap-4 justify-center sm:justify-start">
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
          <div className="flex items-center gap-4 justify-center sm:justify-end">
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
