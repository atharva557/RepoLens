import { BrowserRouter, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import Loading from "./pages/Loading";
import Dashboard from "./pages/Dashboard";
import BugHotspots from "./pages/BugHotspots";
import DeveloperProfile from "./pages/DeveloperProfile";
import Navbar from "./components/Navbar";

// Smoke-test shell wired to the real UI pages.
export default function App() {
  return (
    <BrowserRouter>
      <Navbar />
      <div className="pt-[52px]">
        <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/loading" element={<Loading />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/hotspots" element={<BugHotspots />} />
        <Route path="/profile" element={<DeveloperProfile />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
