import { Link, useLocation } from "react-router-dom";
import { useState, useContext } from "react";
import { ThemeContext } from "../App";

export default function Navbar() {
  const location = useLocation();
  const searchParams = new URLSearchParams(location.search);
  const repo = searchParams.get("repo");
  const user = searchParams.get("user");
  const { theme, setTheme } = useContext(ThemeContext);
  const [showSettings, setShowSettings] = useState(false);

  const path = location.pathname;
  const isIndigo = path === "/profile";

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
  ];

  // Theme styling declarations
  const headerBg = isIndigo 
    ? "bg-[#1a1a1a]/80 border-[rgba(255,255,255,0.05)]" 
    : "bg-surface border-outline-variant";

  const brandText = isIndigo
    ? "bg-gradient-to-r from-[#c0c1ff] to-[#ddb7ff] bg-clip-text text-transparent"
    : "text-primary";

  const brandIcon = isIndigo ? "lens_blur" : "analytics";

  return (
    <header className={`fixed top-0 left-0 right-0 z-50 backdrop-blur-xl border-b h-[52px] transition-colors duration-300 ${headerBg}`}>
      <div className="flex justify-between items-center w-full px-gutter max-w-container-max mx-auto h-full">
        {/* Brand */}
        <Link 
          to={"/" + getQueryString({ repo, user })}
          className="font-code text-heading-md font-bold flex items-center gap-2"
        >
          <span className={`material-symbols-outlined text-[20px] ${!isIndigo ? "text-primary" : "text-[c0c1ff]"}`}>
            {brandIcon}
          </span>
          <span className={`font-bold transition-all duration-300 ${brandText}`}>
            RepoLens
          </span>
        </Link>

        {/* Navigation Items */}
        <nav className="flex items-center gap-4 md:gap-6">
          {navItems.map((item) => {
            const isActive = path === item.path;
            
            let linkClass = "font-label text-label transition-colors duration-200 py-1 px-2 rounded-sm ";
            if (isIndigo) {
              linkClass += isActive
                ? "text-[#c0c1ff] font-bold border-b-2 border-[#c0c1ff] pb-0.5 rounded-none"
                : "text-[#c7c4d7] hover:text-[#c0c1ff] hover:bg-surface-container-high";
            } else {
              linkClass += isActive
                ? "text-primary font-bold border-b-2 border-primary pb-0.5 rounded-none"
                : "text-on-surface-variant hover:text-primary hover:bg-surface-container-high";
            }

            return (
              <Link key={item.label} to={item.to} className={linkClass}>
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Settings Dropdown */}
        <div className="flex items-center gap-4">
          <div className="relative">
            <button 
              onClick={() => setShowSettings(!showSettings)}
              className="p-1 rounded-full hover:bg-surface-container-high transition-colors text-on-surface-variant flex items-center justify-center"
              aria-label="Settings"
            >
              <span className="material-symbols-outlined text-[20px]">settings</span>
            </button>
            
            {showSettings && (
              <div className="absolute right-0 mt-2 w-40 bg-surface border border-outline-variant rounded-md shadow-lg overflow-hidden z-50">
                <div className="py-1">
                  <button
                    onClick={() => { setTheme("dark"); setShowSettings(false); }}
                    className={`w-full text-left px-4 py-2 text-sm font-code flex items-center gap-2 hover:bg-surface-container-high ${theme === "dark" ? "text-primary font-bold" : "text-on-surface"}`}
                  >
                    <span className="material-symbols-outlined text-[16px]">dark_mode</span>
                    Dark Mode
                  </button>
                  <button
                    onClick={() => { setTheme("light"); setShowSettings(false); }}
                    className={`w-full text-left px-4 py-2 text-sm font-code flex items-center gap-2 hover:bg-surface-container-high ${theme === "light" ? "text-primary font-bold" : "text-on-surface"}`}
                  >
                    <span className="material-symbols-outlined text-[16px]">light_mode</span>
                    Light Mode
                  </button>
                  <button
                    onClick={() => { setTheme("grey"); setShowSettings(false); }}
                    className={`w-full text-left px-4 py-2 text-sm font-code flex items-center gap-2 hover:bg-surface-container-high ${theme === "grey" ? "text-primary font-bold" : "text-on-surface"}`}
                  >
                    <span className="material-symbols-outlined text-[16px]">contrast</span>
                    Grey Mode
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
