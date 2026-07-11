import { BrowserRouter, Route, Routes } from "react-router-dom";
import { useState, useEffect, createContext } from "react";
import Home from "./pages/Home";
import Loading from "./pages/Loading";
import Dashboard from "./pages/Dashboard";
import BugHotspots from "./pages/BugHotspots";
import DeveloperProfile from "./pages/DeveloperProfile";
import PRReview from "./pages/PRReview";
import Status from "./pages/Status";
import Navbar from "./components/Navbar";
import { loadGlobalSettings, saveGlobalSettings } from "./lib/settings";

export const ThemeContext = createContext();

// Smoke-test shell wired to the real UI pages.
export default function App() {
  const [settings, setSettings] = useState(() => loadGlobalSettings());

  useEffect(() => {
    const { theme } = settings;
    if (theme === "dark") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = theme;
    }
  }, [settings.theme]);

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
      <BrowserRouter>
        <Navbar />
        <div className="pt-[52px]">
          <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/loading" element={<Loading />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/hotspots" element={<BugHotspots />} />
          <Route path="/profile" element={<DeveloperProfile />} />
          <Route path="/pr-review" element={<PRReview />} />
          <Route path="/status" element={<Status />} />
          </Routes>
        </div>
      </BrowserRouter>
    </ThemeContext.Provider>
  );
}
