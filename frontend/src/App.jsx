import { BrowserRouter, Route, Routes } from "react-router-dom";
import { useState, useEffect, useContext } from "react";
import Home from "./pages/Home";
import Loading from "./pages/Loading";
import Dashboard from "./pages/Dashboard";
import BugHotspots from "./pages/BugHotspots";
import DeveloperProfile from "./pages/DeveloperProfile";
import PRReview from "./pages/PRReview";
import Status from "./pages/Status";
import Login from "./pages/Login";
import Navbar from "./components/Navbar";
import { loadGlobalSettings, saveGlobalSettings } from "./lib/settings";
import { ThemeContext, accentThemeCss } from "./lib/theme";
import { AuthContext, AuthProvider } from "./lib/auth";

// Routes sit behind the auth gate: in multiuser mode an anonymous visitor
// gets the Login wall on every URL (and lands on the URL they asked for once
// signed in); single-user mode renders routes directly, exactly as before.
function Gate() {
  const { mode, user } = useContext(AuthContext);
  if (mode === "loading") return null; // one fast local probe; avoid a flash
  if (mode === "multiuser" && !user) return <Login />;
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/loading" element={<Loading />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/hotspots" element={<BugHotspots />} />
      <Route path="/profile" element={<DeveloperProfile />} />
      <Route path="/pr-review" element={<PRReview />} />
      <Route path="/status" element={<Status />} />
    </Routes>
  );
}

// Smoke-test shell wired to the real UI pages.
export default function App() {
  const [settings, setSettings] = useState(() => loadGlobalSettings());

  // theme: dark | light | system. "system" resolves against the OS preference
  // and re-resolves live when it changes.
  useEffect(() => {
    const apply = () => {
      const { theme } = settings;
      const resolved =
        theme === "system"
          ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
          : theme;
      if (resolved === "dark") {
        delete document.documentElement.dataset.theme;
      } else {
        document.documentElement.dataset.theme = resolved;
      }
    };
    apply();
    if (settings.theme === "system") {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      mq.addEventListener("change", apply);
      return () => mq.removeEventListener("change", apply);
    }
  }, [settings.theme]);

  // accent recolors the whole app — primary, borders, muted text, glows — via
  // an injected per-theme palette (see accentThemeCss). Amber = no override,
  // keeping the hand-tuned default theme exactly as designed.
  useEffect(() => {
    let tag = document.getElementById("accent-theme");
    const css = accentThemeCss(settings.accent, settings.accentColor);
    if (!css) {
      if (tag) tag.remove();
      return;
    }
    if (!tag) {
      tag = document.createElement("style");
      tag.id = "accent-theme";
      document.head.appendChild(tag);
    }
    tag.textContent = css;
  }, [settings.accent, settings.accentColor]);

  const saveSettings = (newSettings) => {
    setSettings(newSettings);
    saveGlobalSettings(newSettings);
  };

  return (
    <ThemeContext.Provider value={{
      settings,
      saveSettings,
      theme: settings.theme,
      setTheme: (newTheme) => saveSettings({ ...settings, theme: newTheme })
    }}>
      <AuthProvider>
        <BrowserRouter>
          <Navbar />
          <div className="pt-[52px]">
            <Gate />
          </div>
        </BrowserRouter>
      </AuthProvider>
    </ThemeContext.Provider>
  );
}

