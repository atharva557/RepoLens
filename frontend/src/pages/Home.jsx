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
  const [profiles, setProfiles] = useState([]);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    Promise.all([
      getJSON("/repos").catch(() => ({ repos: [] })),
      getJSON("/profiles").catch(() => ({ profiles: [] })),
      getJSON("/health").catch(() => null),
    ])
      .then(([reposData, profilesData, healthData]) => {
        setRepos(reposData.repos || []);
        setProfiles(profilesData.profiles || []);
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
    <div className="min-h-[calc(100vh-52px)] bg-[#0e0e0e] text-on-surface flex flex-col justify-between">
      <main className="flex-grow flex items-center justify-center px-gutter pt-8 pb-12">
        <div className="w-full max-w-[720px] py-6 space-y-8">
          {/* Branding Area */}
          <div className="text-center space-y-4">
            <div className="inline-flex items-center gap-2 px-3 py-1 bg-surface-container-high border border-outline-variant rounded-sm">
              <span className="text-primary font-code font-bold">◈</span>
              <span className="font-code text-heading-md font-bold text-on-surface">RepoLens Dashboard</span>
            </div>
            <h1 className="font-heading-lg text-4xl md:text-5xl text-primary font-bold tracking-tight leading-tight">
              Understand any GitHub repository
            </h1>
            <p className="font-body text-body text-on-surface-variant max-w-[520px] mx-auto leading-relaxed">
              Analyze contributions, structural hotspots, code complexity, and commit quality in seconds.
            </p>
          </div>

          {/* Input Section */}
          <div className="space-y-3">
            <form onSubmit={handleFormSubmit} className="relative group">
              <div className="absolute -inset-1 bg-primary/10 blur opacity-0 group-focus-within:opacity-100 transition duration-500 rounded-lg"></div>
              <div className="relative flex items-center bg-surface-container-lowest border border-outline-variant rounded-sm overflow-hidden focus-within:border-primary transition-colors">
                <div className="pl-4 pr-2 text-on-surface-variant flex items-center">
                  <span className="material-symbols-outlined text-[18px]">content_paste</span>
                </div>
                <input
                  type="text"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  disabled={submitting}
                  className="w-full bg-transparent border-none text-on-surface font-code text-code py-4 focus:ring-0 focus:outline-none placeholder:text-surface-container-highest placeholder:opacity-50"
                  placeholder="https://github.com/owner/repository or local path"
                />
                <button
                  type="submit"
                  disabled={submitting || !url.trim()}
                  className="bg-primary hover:bg-primary-container text-on-primary font-bold px-6 py-4 flex items-center gap-2 transition-all active:scale-95 whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span>{submitting ? "Analyzing..." : "Analyze"}</span>
                  <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                </button>
              </div>
            </form>

            {error && (
              <div className="p-3 bg-error-container/20 border border-error-container/50 text-error rounded-sm font-code text-xs flex items-start gap-2">
                <span className="material-symbols-outlined text-sm mt-0.5">error</span>
                <span>{error}</span>
              </div>
            )}
          </div>

          {/* Try an Example */}
          <div className="space-y-2">
            <div className="font-code text-[10px] text-surface-container-highest tracking-widest uppercase">
              // TRY AN EXAMPLE
            </div>
            <div className="flex flex-wrap gap-2">
              {["pallets/flask", "expressjs/express", "facebook/react"].map((example) => (
                <button
                  key={example}
                  onClick={() => {
                    setUrl(example);
                    handleAnalyze(example);
                  }}
                  disabled={submitting}
                  className="font-code text-label bg-surface-container border border-outline-variant px-3 py-1.5 hover:bg-surface-container-high hover:border-primary transition-colors text-on-surface-variant hover:text-primary rounded-sm cursor-pointer disabled:opacity-50"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>

          {/* Discovery Grid: Repositories & Profiles */}
          <div className="grid grid-cols-1 md:grid-cols-12 gap-8 pt-6 border-t border-outline-variant">
            {/* Left: Repos analyzed */}
            <div className="md:col-span-7 space-y-4">
              <div className="font-code text-[10px] text-surface-container-highest tracking-widest uppercase flex items-center gap-2">
                <span className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse"></span>
                // RECENT ANALYSES
              </div>
              
              {repos.length === 0 ? (
                <div className="p-6 bg-surface-container/30 border border-outline-variant/30 rounded-sm text-center">
                  <p className="text-on-surface-variant font-code text-xs">No repositories analyzed yet.</p>
                </div>
              ) : (
                <div className="space-y-1 max-h-[300px] overflow-y-auto pr-1 scrollbar-thin">
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
                        className="flex items-center justify-between group px-3 py-2 bg-transparent hover:bg-surface-container transition-colors border border-transparent hover:border-outline-variant rounded-sm"
                      >
                        <div className="flex flex-col">
                          <span className="font-code text-code text-on-surface group-hover:text-primary transition-colors">
                            {r.repo}
                          </span>
                          <span className="text-[10px] text-on-surface-variant flex items-center gap-2 mt-0.5">
                            <span>{r.commits} commits</span>
                            {r.hotspots && <span className="text-primary font-bold">● hotspots</span>}
                            {r.commit_quality && <span className="text-tertiary font-bold">● quality</span>}
                          </span>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="font-code text-[11px] text-on-surface-variant">
                            {lastActive ? timeAgo(lastActive) : "analyzed"}
                          </span>
                          <span className="material-symbols-outlined text-surface-container-highest group-hover:text-primary transition-colors">
                            trending_flat
                          </span>
                        </div>
                      </a>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Right: Profiles analyzed */}
            <div className="md:col-span-5 space-y-4">
              <div className="font-code text-[10px] text-surface-container-highest tracking-widest uppercase flex items-center gap-2">
                <span className="w-1.5 h-1.5 bg-tertiary rounded-full"></span>
                // DEVELOPER PROFILES
              </div>

              {profiles.length === 0 ? (
                <div className="p-6 bg-surface-container/30 border border-outline-variant/30 rounded-sm text-center">
                  <p className="text-on-surface-variant font-code text-xs">No developer profiles built yet.</p>
                </div>
              ) : (
                <div className="space-y-1 max-h-[300px] overflow-y-auto pr-1 scrollbar-thin">
                  {profiles.map((p) => (
                    <a
                      key={p.username}
                      href={`/profile?user=${p.username}`}
                      onClick={(e) => {
                        e.preventDefault();
                        navigate(`/profile?user=${p.username}`);
                      }}
                      className="flex items-center justify-between group px-3 py-2 bg-transparent hover:bg-surface-container transition-colors border border-transparent hover:border-outline-variant rounded-sm"
                    >
                      <div className="flex flex-col">
                        <span className="font-code text-code text-on-surface group-hover:text-tertiary transition-colors">
                          @{p.username}
                        </span>
                        <span className="text-[10px] text-on-surface-variant mt-0.5">
                          {p.primary_type || "Developer"}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-code text-[10px] text-on-surface-variant">
                          {timeAgo(p.generated_at)}
                        </span>
                        <span className="material-symbols-outlined text-surface-container-highest group-hover:text-tertiary transition-colors">
                          trending_flat
                        </span>
                      </div>
                    </a>
                  ))}
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
