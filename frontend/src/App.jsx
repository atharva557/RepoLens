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

export const ThemeContext = createContext();

// Smoke-test shell wired to the real UI pages.
export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "dark");

  useEffect(() => {
    if (theme === "dark") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = theme;
    }
    localStorage.setItem("theme", theme);
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
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
