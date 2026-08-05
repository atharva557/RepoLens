import { Link, useLocation, useNavigate } from "react-router-dom";
import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { AuthContext } from "../lib/auth";
import { getJSON } from "../lib/api";

// ─── helpers ────────────────────────────────────────────────────────────────

function repoUrl(path, repo) {
  return repo ? `${path}?repo=${encodeURIComponent(repo)}` : path;
}

function navLinkClass(active) {
  return [
    "font-medium text-sm px-3 py-1.5 transition-colors duration-200",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 rounded-lg",
    active ? "text-primary bg-primary/10" : "text-on-surface-variant hover:text-on-surface hover:bg-surface-container-highest",
  ].join(" ");
}

function RepoSuggestions({ id, suggestions, activeIndex, onSelect }) {
  return (
    <ul
      id={id}
      role="listbox"
      className="absolute left-0 right-0 top-[calc(100%+6px)] z-50 overflow-hidden rounded-lg border border-outline-variant bg-surface-container shadow-xl"
    >
      {suggestions.map((item, index) => (
        <li key={item.repo} role="presentation">
          <button
            id={`${id}-option-${index}`}
            type="button"
            role="option"
            aria-selected={index === activeIndex}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onSelect(item.repo)}
            className={`flex w-full items-center gap-2 px-3 py-2.5 text-left font-code text-xs transition-colors ${
              index === activeIndex
                ? "bg-primary/15 text-primary"
                : "text-on-surface hover:bg-surface-container-high hover:text-primary"
            }`}
          >
            <span className="material-symbols-outlined text-[16px] opacity-70">folder</span>
            <span className="truncate">{item.repo}</span>
            <span className="ml-auto shrink-0 text-[10px] text-on-surface-variant">
              {item.commits ?? 0} commits
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

// ─── sub-components ─────────────────────────────────────────────────────────

// Removed ActiveUnderline as requested

/** Single row inside the avatar dropdown. */
function DropdownItem({ icon, label, onClick, danger = false, as: Tag = "button", to }) {
  const base =
    "w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors duration-150 cursor-pointer text-left";
  const color = danger
    ? "text-red-400 hover:bg-red-500/10"
    : "text-on-surface hover:bg-surface-container-high";

  if (Tag === Link) {
    return (
      <Link to={to} onClick={onClick} className={`${base} ${color}`}>
        <span className="material-symbols-outlined text-[18px] shrink-0 opacity-70">
          {icon}
        </span>
        {label}
      </Link>
    );
  }

  return (
    <button type="button" onClick={onClick} className={`${base} ${color}`}>
      <span
        className={`material-symbols-outlined text-[18px] shrink-0 ${
          danger ? "opacity-80" : "opacity-70"
        }`}
      >
        {icon}
      </span>
      {label}
    </button>
  );
}

// ─── main component ──────────────────────────────────────────────────────────

export default function Navbar() {
  const location = useLocation();
  const navigate = useNavigate();
  const repo = new URLSearchParams(location.search).get("repo");
  const path = location.pathname;

  const { mode, user: account, logout } = useContext(AuthContext);
  const isLoggedIn = mode === "single" || Boolean(account);
  const hasRepo = Boolean(repo);

  // ui state
  const [mobileOpen,    setMobileOpen]    = useState(false);
  const [avatarOpen,    setAvatarOpen]    = useState(false);
  const [searchValue,   setSearchValue]   = useState("");
  const [repos,         setRepos]         = useState([]);
  const [searchFocused, setSearchFocused] = useState(false);
  const [activeIndex,   setActiveIndex]   = useState(-1);

  const avatarRef   = useRef(null);
  const dropdownRef = useRef(null);
  const desktopSearchRef = useRef(null);
  const mobileSearchRef  = useRef(null);

  const loadRepositories = useCallback(() => {
    if (!isLoggedIn) {
      setRepos([]);
      return;
    }

    getJSON("/repos", { ttl: 30_000 })
      .then((data) => setRepos(data.repos || []))
      .catch(() => setRepos([]));
  }, [isLoggedIn]);

  useEffect(() => {
    loadRepositories();
  }, [loadRepositories]);

  // Close avatar dropdown on outside click / Escape
  useEffect(() => {
    if (!avatarOpen) return;

    function handleOutside(e) {
      if (
        avatarRef.current &&
        !avatarRef.current.contains(e.target) &&
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target)
      ) {
        setAvatarOpen(false);
      }
    }

    function handleKey(e) {
      if (e.key === "Escape") setAvatarOpen(false);
    }

    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleKey);
    };
  }, [avatarOpen]);

  // "/" shortcut focuses the visible search input.
  useEffect(() => {
    function onKey(e) {
      if (
        e.key === "/" &&
        document.activeElement.tagName !== "INPUT" &&
        document.activeElement.tagName !== "TEXTAREA"
      ) {
        e.preventDefault();
        if (window.matchMedia("(min-width: 768px)").matches) {
          desktopSearchRef.current?.focus();
          return;
        }
        setMobileOpen(true);
        requestAnimationFrame(() => mobileSearchRef.current?.focus());
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const closeAll = () => {
    setMobileOpen(false);
    setAvatarOpen(false);
    setSearchFocused(false);
    setActiveIndex(-1);
  };

  const suggestions = searchValue.trim()
    ? repos
      .filter((item) => item?.repo?.toLowerCase().includes(searchValue.trim().toLowerCase()))
      .sort((a, b) => {
        const query = searchValue.trim().toLowerCase();
        const aStartsWithQuery = a.repo.toLowerCase().startsWith(query);
        const bStartsWithQuery = b.repo.toLowerCase().startsWith(query);
        if (aStartsWithQuery !== bStartsWithQuery) return aStartsWithQuery ? -1 : 1;
        return a.repo.localeCompare(b.repo);
      })
      .slice(0, 5)
    : [];

  const selectRepository = (selectedRepo) => {
    setSearchValue("");
    closeAll();
    navigate(repoUrl("/dashboard", selectedRepo));
  };

  const handleSearchChange = (event) => {
    setSearchValue(event.target.value);
    setSearchFocused(true);
    setActiveIndex(-1);
  };

  const handleSearchKeyDown = (event) => {
    if (event.key === "ArrowDown" && suggestions.length) {
      event.preventDefault();
      setActiveIndex((index) => (index + 1) % suggestions.length);
    } else if (event.key === "ArrowUp" && suggestions.length) {
      event.preventDefault();
      setActiveIndex((index) => (index <= 0 ? suggestions.length - 1 : index - 1));
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      selectRepository(suggestions[activeIndex].repo);
    } else if (event.key === "Escape") {
      setSearchFocused(false);
      setActiveIndex(-1);
    }
  };

  // Display name / avatar initial
  const displayName =
    account?.github_login || account?.email || (mode === "single" ? "You" : "?");
  const avatarInitial = displayName.slice(0, 1).toUpperCase();

  // Top-level nav links
  const navLinks = [
    { label: "Home",             to: "/",          active: path === "/"          },
    { label: "Dashboard",        to: hasRepo ? repoUrl("/dashboard", repo) : "/dashboard",   active: path === "/dashboard"  },
    { label: "PR Reviews",       to: hasRepo ? repoUrl("/pr-review", repo) : "/pr-review",   active: path === "/pr-review"  },
    { label: "Developer Profile", to: "/profile",  active: path === "/profile"   },
  ];

  return (
    <header className="fixed top-0 left-0 right-0 z-50 h-[52px] backdrop-blur-xl border-b border-outline-variant bg-surface transition-colors duration-300">
      <div className="flex items-center justify-between w-full h-full px-gutter max-w-container-max mx-auto gap-4 lg:gap-6">

        {/* ── Logo ──────────────────────────────────────────────────────── */}
        <div className="flex-1 flex items-center justify-start">
          <Link
            to="/"
            onClick={closeAll}
            className="font-code text-heading-md font-bold flex items-center gap-2 shrink-0"
          >
            <span className="material-symbols-outlined text-[20px] text-primary">analytics</span>
            <span className="font-bold transition-all duration-300 glow-text text-primary">RepoLens</span>
          </Link>
        </div>

        {/* ── Desktop nav links ──────────────────────────────────────────── */}
        <div className="flex-shrink-0 flex items-center justify-center">
          {isLoggedIn && (
            <nav className="hidden md:flex items-center gap-6 lg:gap-8 h-full" aria-label="Main navigation">
              {navLinks.map(({ label, to, active }) => (
                <Link key={label} to={to} onClick={closeAll} className={navLinkClass(active)}>
                  {label}
                </Link>
              ))}
            </nav>
          )}
        </div>

        {/* ── Right section ─────────────────────────────────────────────── */}
        <div className="flex-1 flex items-center justify-end gap-3">

          {/* Search bar */}
          {isLoggedIn && (
            <div className="relative hidden md:block group">
              <input
                ref={desktopSearchRef}
                type="text"
                value={searchValue}
                onChange={handleSearchChange}
                onFocus={() => {
                  loadRepositories();
                  setSearchFocused(true);
                }}
                onBlur={() => setSearchFocused(false)}
                onKeyDown={handleSearchKeyDown}
                placeholder="Search repositories..."
                aria-label="Search repositories"
                role="combobox"
                aria-autocomplete="list"
                aria-expanded={searchFocused && suggestions.length > 0}
                aria-controls="desktop-repo-suggestions"
                aria-activedescendant={activeIndex >= 0 ? `desktop-repo-suggestions-option-${activeIndex}` : undefined}
                className="peer w-[340px] rounded-md py-1.5 pl-3 pr-10 text-sm outline-none border transition-all bg-surface-container-lowest border-outline-variant text-on-surface placeholder:text-on-surface-variant/60 focus:border-primary focus:ring-1 focus:ring-primary/40 focus:bg-surface-container-highest hover:bg-surface-container"
              />
              <kbd
                className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 px-1.5 py-0.5 rounded font-mono text-[10px] font-semibold transition-colors bg-surface-container-highest border border-outline-variant text-on-surface-variant peer-focus:bg-primary/10 peer-focus:border-primary/30 peer-focus:text-primary"
              >
                /
              </kbd>
              {searchFocused && suggestions.length > 0 && (
                <RepoSuggestions
                  id="desktop-repo-suggestions"
                  suggestions={suggestions}
                  activeIndex={activeIndex}
                  onSelect={selectRepository}
                />
              )}
            </div>
          )}

          {/* ── Avatar + dropdown ─────────────────────────────────────────── */}
          {isLoggedIn && (
            <div className="relative">

              {/* Avatar button */}
              <button
                ref={avatarRef}
                type="button"
                aria-haspopup="menu"
                aria-expanded={avatarOpen}
                aria-label="Account menu"
                onClick={() => setAvatarOpen((v) => !v)}
                className={[
                  "w-8 h-8 rounded-full flex items-center justify-center",
                  "bg-primary/15 border-2 text-primary text-[13px] font-bold uppercase",
                  "transition-colors duration-200 cursor-pointer select-none",
                  avatarOpen
                    ? "border-primary"
                    : "border-primary/30 hover:border-primary/70",
                ].join(" ")}
              >
                {avatarInitial}
              </button>

              {/* Dropdown panel */}
              <div
                ref={dropdownRef}
                role="menu"
                aria-label="Account options"
                style={{
                  opacity: avatarOpen ? 1 : 0,
                  transform: avatarOpen ? "translateY(0) scale(1)" : "translateY(-6px) scale(0.97)",
                  pointerEvents: avatarOpen ? "auto" : "none",
                  transition: "opacity 180ms ease, transform 180ms cubic-bezier(0.16,1,0.3,1)",
                }}
                className="absolute right-0 top-[calc(100%+8px)] w-56 rounded-xl border border-outline-variant bg-surface-container shadow-2xl overflow-hidden z-50"
              >
                {/* "Signed in as" header */}
                <div className="px-4 py-3 border-b border-outline-variant">
                  <p className="text-[10px] uppercase tracking-widest text-on-surface-variant font-semibold mb-0.5">
                    Signed in as
                  </p>
                  <p className="text-sm font-semibold text-on-surface truncate">
                    {displayName}
                  </p>
                </div>

                {/* Settings + Preferences */}
                <div className="py-1 border-b border-outline-variant">
                  <DropdownItem as={Link} to="/preferences" icon="tune"     label="Preferences" onClick={closeAll} />
                  <DropdownItem as={Link} to="/settings"    icon="settings" label="Settings"    onClick={closeAll} />
                </div>

                {/* Logout */}
                <div className="py-1">
                  <DropdownItem
                    icon="logout"
                    label="Logout"
                    danger
                    onClick={() => { setAvatarOpen(false); logout(); }}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Mobile hamburger */}
          {isLoggedIn && (
            <button
              type="button"
              className="md:hidden flex items-center justify-center text-on-surface-variant hover:text-primary transition-colors h-9 w-9 rounded bg-surface-container-high border border-outline-variant hover:border-primary"
              onClick={() => setMobileOpen((v) => !v)}
              aria-label="Toggle menu"
            >
              <span className="material-symbols-outlined text-[18px]">
                {mobileOpen ? "close" : "menu"}
              </span>
            </button>
          )}
        </div>
      </div>

      {/* ── Mobile menu ──────────────────────────────────────────────────── */}
      {isLoggedIn && mobileOpen && (
        <div className="md:hidden absolute top-[52px] left-0 right-0 bg-surface border-b border-outline-variant shadow-lg py-3 px-4 flex flex-col gap-1 z-40">

          {/* Search */}
          <div className="relative mb-2">
            <input
              ref={mobileSearchRef}
              type="text"
              value={searchValue}
              onChange={handleSearchChange}
              onFocus={() => {
                loadRepositories();
                setSearchFocused(true);
              }}
              onBlur={() => setSearchFocused(false)}
              onKeyDown={handleSearchKeyDown}
              placeholder="Search repositories..."
              aria-label="Search repositories"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={searchFocused && suggestions.length > 0}
              aria-controls="mobile-repo-suggestions"
              aria-activedescendant={activeIndex >= 0 ? `mobile-repo-suggestions-option-${activeIndex}` : undefined}
              className="w-full bg-surface-container-lowest text-on-surface border border-outline-variant rounded-md py-1.5 pl-3 pr-8 text-sm placeholder:text-on-surface-variant/60 focus:outline-none focus:ring-2 focus:ring-primary/60"
            />
            <kbd className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-outline-variant bg-surface-container-highest px-1 py-0.5 font-mono text-[10px] text-on-surface-variant">
              /
            </kbd>
            {searchFocused && suggestions.length > 0 && (
              <RepoSuggestions
                id="mobile-repo-suggestions"
                suggestions={suggestions}
                activeIndex={activeIndex}
                onSelect={selectRepository}
              />
            )}
          </div>

          {/* Nav links */}
          {navLinks.map(({ label, to, active }) => (
            <Link
              key={label}
              to={to}
              onClick={closeAll}
              className={`px-2 py-2 rounded text-sm font-medium transition-colors ${
                active
                  ? "text-primary font-bold"
                  : "text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high"
              }`}
            >
              {label}
            </Link>
          ))}

          {/* Account actions */}
          <div className="border-t border-outline-variant mt-2 pt-2 flex flex-col gap-1">
            <Link
              to="/preferences"
              onClick={closeAll}
              className="flex items-center gap-2 px-2 py-2 text-sm text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high rounded transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">tune</span>
              Preferences
            </Link>
            <Link
              to="/settings"
              onClick={closeAll}
              className="flex items-center gap-2 px-2 py-2 text-sm text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high rounded transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">settings</span>
              Settings
            </Link>
            <button
              type="button"
              onClick={() => { closeAll(); logout(); }}
              className="flex items-center gap-2 px-2 py-2 text-sm text-red-400 hover:bg-red-500/10 rounded transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">logout</span>
              Logout
            </button>
          </div>
        </div>
      )}
    </header>
  );
}
