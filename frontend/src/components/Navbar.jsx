import { Link, useLocation } from "react-router-dom";
import { useContext, useState } from "react";
import SettingsDrawer from "./SettingsDrawer";
import { AuthContext } from "../lib/auth";

export default function Navbar() {
  const location = useLocation();
  const searchParams = new URLSearchParams(location.search);
  const repo = searchParams.get("repo");
  const user = searchParams.get("user");
  const [showSettings, setShowSettings] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  // session (multiuser mode); `user` above is a URL param, hence `account`
  const { mode, user: account, logout } = useContext(AuthContext);

  const path = location.pathname;

  // Build query string helper
  const getQueryString = (params) => {
    const newParams = new URLSearchParams();
    if (params.repo) newParams.set("repo", params.repo);
    if (params.user) newParams.set("user", params.user);
    const str = newParams.toString();
    return str ? `?${str}` : "";
  };

  const navItems = [
    {
      label: "Home",
      path: "/",
      to: "/" + getQueryString({ repo, user }),
    },
    {
      label: "Dashboard",
      path: "/dashboard",
      to: "/dashboard" + getQueryString({ repo, user }),
    },
    {
      label: "Bug Hotspots",
      path: "/hotspots",
      to: "/hotspots" + getQueryString({ repo, user }),
    },
    {
      label: "Developer Profile",
      path: "/profile",
      to: "/profile" + getQueryString({ repo, user }),
    },
    {
      label: "PR Review",
      path: "/pr-review",
      to: "/pr-review" + getQueryString({ repo, user }),
    },
    // /status stays routable but deliberately unlisted — an admin view,
    // reached by typing the URL.
  ];

  // Theme styling declarations
  const headerBg = "bg-surface border-outline-variant";
  const brandText = "text-primary";
  const brandIcon = "analytics";

  return (
    <header className={`fixed top-0 left-0 right-0 z-50 backdrop-blur-xl border-b h-[52px] transition-colors duration-300 ${headerBg}`}>
      <div className="flex justify-between items-center w-full px-gutter max-w-container-max mx-auto h-full">
        {/* Brand */}
        <Link
          to={"/" + getQueryString({ repo, user })}
          className="font-code text-heading-md font-bold flex items-center gap-2"
        >
          <span className="material-symbols-outlined text-[20px] text-primary">
            {brandIcon}
          </span>
          <span className={`font-bold transition-all duration-300 glow-text ${brandText}`}>
            RepoLens
          </span>
        </Link>

        {/* Navigation Items (Desktop) */}
        <nav className="hidden md:flex items-center gap-4 md:gap-6">
          {navItems.map((item) => {
            const isActive = path === item.path;

            let linkClass = "font-label text-label transition-colors duration-200 py-1 px-2 rounded-sm ";
            linkClass += isActive
              ? "text-primary font-bold border-b-2 border-primary pb-0.5 rounded-none"
              : "text-on-surface-variant hover:text-primary hover:bg-surface-container-high";

            return (
              <Link key={item.label} to={item.to} className={linkClass}>
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Settings Button (prototype: labeled, bordered, active while open) */}
        <div className="flex items-center gap-4">
          {/* signed-in account chip (multiuser mode only) */}
          {mode === "multiuser" && account && (
            <div className="flex items-center gap-2">
              <div
                className="w-7 h-7 rounded-full bg-primary/15 border border-primary/30 flex items-center justify-center text-primary text-[12px] font-bold uppercase"
                title={account.email || account.github_login || "signed in"}
              >
                {(account.github_login || account.email || "?").slice(0, 1)}
              </div>
              <span className="hidden md:inline text-label text-on-surface-variant max-w-[160px] truncate">
                {account.github_login || account.email}
              </span>
              <button
                onClick={logout}
                title="Sign out"
                className="text-on-surface-variant hover:text-primary transition-colors flex items-center"
              >
                <span className="material-symbols-outlined text-[18px]">logout</span>
              </button>
            </div>
          )}

          <button
            onClick={() => setShowSettings(true)}
            className={`bg-surface-container-high border h-9 px-3 rounded-[4px] flex items-center gap-2 text-label font-bold text-on-surface-variant hover:bg-surface-container-highest hover:border-primary transition-all group cursor-pointer ${showSettings ? "bg-primary/10 border-primary" : "border-outline-variant"
              }`}
            aria-label="Settings"
          >
            <span className="material-symbols-outlined text-[18px] group-hover:text-primary transition-colors">
              settings
            </span>
            <span className="hidden sm:inline">Settings</span>
          </button>

          <SettingsDrawer open={showSettings} onClose={() => setShowSettings(false)} />

          {/* Mobile Menu Toggle */}
          <button
            className="md:hidden flex items-center justify-center text-on-surface-variant hover:text-primary transition-colors h-9 w-9 rounded bg-surface-container-high border border-outline-variant hover:border-primary"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle Menu"
          >
            <span className="material-symbols-outlined text-[18px]">
              {mobileMenuOpen ? "close" : "menu"}
            </span>
          </button>
        </div>
      </div>

      {/* Mobile Menu Dropdown */}
      {mobileMenuOpen && (
        <div className="md:hidden absolute top-[52px] left-0 right-0 bg-surface border-b border-outline-variant shadow-lg py-2 px-4 flex flex-col gap-1 z-40">
          {navItems.map((item) => {
            const isActive = path === item.path;

            let linkClass = "font-label text-label transition-colors duration-200 py-3 px-4 rounded-sm flex items-center w-full ";
            linkClass += isActive
              ? "text-primary font-bold bg-primary/5 border-l-2 border-primary"
              : "text-on-surface-variant hover:text-primary hover:bg-surface-container-high";

            return (
              <Link
                key={item.label}
                to={item.to}
                className={linkClass}
                onClick={() => setMobileMenuOpen(false)}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      )}
    </header>
  );
}
