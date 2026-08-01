import { Link, useLocation, useNavigate } from "react-router-dom";
import { useContext, useEffect, useState } from "react";
import SettingsDrawer from "./SettingsDrawer";
import { AuthContext } from "../lib/auth";
import { getJSON } from "../lib/api";

function navClass(active) {
  return `font-label text-label transition-colors duration-200 py-1 px-2 rounded-sm ${
    active
      ? "text-primary font-bold border-b-2 border-primary pb-0.5 rounded-none"
      : "text-on-surface-variant hover:text-primary hover:bg-surface-container-high"
  }`;
}

function repoUrl(path, repo) {
  return repo ? `${path}?repo=${encodeURIComponent(repo)}` : path;
}

export default function Navbar() {
  const location = useLocation();
  const navigate = useNavigate();
  const repo = new URLSearchParams(location.search).get("repo");
  const [showSettings, setShowSettings] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [repoMenuOpen, setRepoMenuOpen] = useState(false);
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const [repos, setRepos] = useState([]);
  const { mode, user: account, logout } = useContext(AuthContext);

  const path = location.pathname;
  const isLoggedIn = mode === "single" || Boolean(account);
  const hasRepo = Boolean(repo);

  useEffect(() => {
    if (!isLoggedIn) return undefined;

    let active = true;
    getJSON("/repos", { ttl: 30_000 })
      .then((data) => {
        if (active) setRepos(data.repos || []);
      })
      .catch(() => {
        // The home page already gives the user a full error/empty state.
        // Navigation should remain usable when the repo list is unavailable.
        if (active) setRepos([]);
      });

    return () => {
      active = false;
    };
  }, [isLoggedIn]);

  const chooseRepo = (selectedRepo) => {
    setRepoMenuOpen(false);
    setMobileMenuOpen(false);
    navigate(repoUrl("/dashboard", selectedRepo));
  };

  const closeMenus = () => {
    setRepoMenuOpen(false);
    setMoreMenuOpen(false);
    setMobileMenuOpen(false);
  };

  const contextualItems = [
    { label: "Bug Hotspots", path: "/hotspots", icon: "local_fire_department" },
    { label: "PR Reviews", path: "/pr-review", icon: "rate_review" },
  ];

  return (
    <header className="fixed top-0 left-0 right-0 z-50 backdrop-blur-xl border-b h-[52px] transition-colors duration-300 bg-surface border-outline-variant">
      <div className="flex justify-between items-center w-full px-gutter max-w-container-max mx-auto h-full">
        <Link to="/" className="font-code text-heading-md font-bold flex items-center gap-2" onClick={closeMenus}>
          <span className="material-symbols-outlined text-[20px] text-primary">analytics</span>
          <span className="font-bold transition-all duration-300 glow-text text-primary">RepoLens</span>
        </Link>

        {isLoggedIn && (
          <nav className="hidden md:flex items-center gap-2 lg:gap-4" aria-label="Main navigation">
            <Link to="/" className={navClass(path === "/")} onClick={closeMenus}>Home</Link>

            <div className="relative">
              <button
                type="button"
                onClick={() => {
                  setRepoMenuOpen(!repoMenuOpen);
                  setMoreMenuOpen(false);
                }}
                aria-expanded={repoMenuOpen}
                aria-haspopup="menu"
                className={`${navClass(path === "/dashboard" || path === "/hotspots" || path === "/pr-review")} flex items-center gap-1`}
              >
                Repositories
                <span className="material-symbols-outlined text-[15px]">expand_more</span>
              </button>
              {repoMenuOpen && (
                <div role="menu" className="absolute top-9 left-0 w-64 rounded-lg border border-outline-variant bg-surface-container shadow-xl overflow-hidden py-1">
                  <p className="px-3 py-2 text-[10px] font-code uppercase tracking-wider text-on-surface-variant">Switch repository</p>
                  {repos.length ? repos.map((item) => (
                    <button
                      type="button"
                      role="menuitem"
                      key={item.repo}
                      onClick={() => chooseRepo(item.repo)}
                      className={`w-full px-3 py-2.5 text-left flex items-center justify-between gap-3 hover:bg-surface-container-high transition-colors ${repo === item.repo ? "text-primary bg-primary/5" : "text-on-surface"}`}
                    >
                      <span className="font-code text-xs truncate">{item.repo}</span>
                      <span className="text-[10px] text-on-surface-variant shrink-0">{item.commits ?? 0} commits</span>
                    </button>
                  )) : (
                    <div className="px-3 py-3 text-xs text-on-surface-variant">No analyzed repositories yet.</div>
                  )}
                  <Link to="/" role="menuitem" onClick={closeMenus} className="block border-t border-outline-variant mt-1 px-3 py-2.5 text-xs font-bold text-primary hover:bg-primary/5">
                    Analyze a repository →
                  </Link>
                </div>
              )}
            </div>

            {hasRepo ? (
              <Link to={repoUrl("/dashboard", repo)} className={navClass(path === "/dashboard")} onClick={closeMenus}>Dashboard</Link>
            ) : (
              <span title="Choose a repository first" className="font-label text-label py-1 px-2 text-on-surface-variant/45 cursor-not-allowed">Dashboard</span>
            )}

            <Link to="/profile" className={navClass(path === "/profile")} onClick={closeMenus}>Developers</Link>

            <div className="relative">
              <button
                type="button"
                onClick={() => {
                  setMoreMenuOpen(!moreMenuOpen);
                  setRepoMenuOpen(false);
                }}
                aria-expanded={moreMenuOpen}
                aria-haspopup="menu"
                className={`${navClass(path === "/hotspots" || path === "/pr-review")} flex items-center gap-1`}
              >
                More
                <span className="material-symbols-outlined text-[15px]">expand_more</span>
              </button>
              {moreMenuOpen && (
                <div role="menu" className="absolute top-9 right-0 w-52 rounded-lg border border-outline-variant bg-surface-container shadow-xl overflow-hidden py-1">
                  <p className="px-3 py-2 text-[10px] font-code uppercase tracking-wider text-on-surface-variant">Repository tools</p>
                  {contextualItems.map((item) => hasRepo ? (
                    <Link key={item.path} to={repoUrl(item.path, repo)} role="menuitem" onClick={closeMenus} className="px-3 py-2.5 flex items-center gap-2 text-xs text-on-surface hover:bg-surface-container-high hover:text-primary">
                      <span className="material-symbols-outlined text-[16px]">{item.icon}</span>{item.label}
                    </Link>
                  ) : (
                    <span key={item.path} title="Choose a repository first" className="px-3 py-2.5 flex items-center gap-2 text-xs text-on-surface-variant/45 cursor-not-allowed">
                      <span className="material-symbols-outlined text-[16px]">{item.icon}</span>{item.label}
                    </span>
                  ))}
                  {!hasRepo && <p className="border-t border-outline-variant mt-1 px-3 py-2 text-[10px] text-on-surface-variant">Choose a repository to unlock these tools.</p>}
                </div>
              )}
            </div>

            {hasRepo && <span className="max-w-36 lg:max-w-48 truncate rounded border border-primary/25 bg-primary/5 px-2 py-1 font-code text-[10px] text-primary" title={`Current repository: ${repo}`}>Repo: {repo}</span>}
          </nav>
        )}

        <div className="flex items-center gap-3">
          {mode === "multiuser" && account && (
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-full bg-primary/15 border border-primary/30 flex items-center justify-center text-primary text-[12px] font-bold uppercase" title={account.email || account.github_login || "signed in"}>
                {(account.github_login || account.email || "?").slice(0, 1)}
              </div>
              <span className="hidden lg:inline text-label text-on-surface-variant max-w-[140px] truncate">{account.github_login || account.email}</span>
              <button onClick={logout} title="Sign out" className="text-on-surface-variant hover:text-primary transition-colors flex items-center"><span className="material-symbols-outlined text-[18px]">logout</span></button>
            </div>
          )}

          <button onClick={() => setShowSettings(true)} className={`bg-surface-container-high border h-9 px-3 rounded-[4px] flex items-center gap-2 text-label font-bold text-on-surface-variant hover:bg-surface-container-highest hover:border-primary transition-all group cursor-pointer ${showSettings ? "bg-primary/10 border-primary" : "border-outline-variant"}`} aria-label="Settings">
            <span className="material-symbols-outlined text-[18px] group-hover:text-primary transition-colors">settings</span>
            <span className="hidden sm:inline">Settings</span>
          </button>
          <SettingsDrawer open={showSettings} onClose={() => setShowSettings(false)} />

          {isLoggedIn && (
            <button className="md:hidden flex items-center justify-center text-on-surface-variant hover:text-primary transition-colors h-9 w-9 rounded bg-surface-container-high border border-outline-variant hover:border-primary" onClick={() => setMobileMenuOpen(!mobileMenuOpen)} aria-label="Toggle Menu">
              <span className="material-symbols-outlined text-[18px]">{mobileMenuOpen ? "close" : "menu"}</span>
            </button>
          )}
        </div>
      </div>

      {isLoggedIn && mobileMenuOpen && (
        <div className="md:hidden absolute top-[52px] left-0 right-0 bg-surface border-b border-outline-variant shadow-lg py-3 px-4 flex flex-col gap-1 z-40">
          <Link to="/" className={navClass(path === "/")} onClick={closeMenus}>Home</Link>
          <p className="pt-3 px-2 text-[10px] font-code uppercase tracking-wider text-on-surface-variant">Repositories</p>
          {repos.length ? repos.map((item) => (
            <button type="button" key={item.repo} onClick={() => chooseRepo(item.repo)} className={`px-2 py-2 text-left font-code text-xs ${repo === item.repo ? "text-primary" : "text-on-surface-variant"}`}>{item.repo}</button>
          )) : <Link to="/" onClick={closeMenus} className="px-2 py-2 text-xs text-primary">Analyze a repository →</Link>}
          {hasRepo ? <Link to={repoUrl("/dashboard", repo)} className={navClass(path === "/dashboard")} onClick={closeMenus}>Dashboard</Link> : <span className="px-2 py-2 text-label text-on-surface-variant/45">Dashboard — choose a repo first</span>}
          <Link to="/profile" className={navClass(path === "/profile")} onClick={closeMenus}>Developers</Link>
          <p className="pt-3 px-2 text-[10px] font-code uppercase tracking-wider text-on-surface-variant">Repository tools</p>
          {contextualItems.map((item) => hasRepo ? <Link key={item.path} to={repoUrl(item.path, repo)} className={navClass(path === item.path)} onClick={closeMenus}>{item.label}</Link> : <span key={item.path} className="px-2 py-2 text-label text-on-surface-variant/45">{item.label} — choose a repo first</span>)}
        </div>
      )}
    </header>
  );
}
