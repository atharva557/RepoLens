import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import Loading from "./pages/Loading";
import Dashboard from "./pages/Dashboard";
import BugHotspots from "./pages/BugHotspots";
import DeveloperProfile from "./pages/DeveloperProfile";

// Plain-text smoke-test shell: a nav bar + one route per prototype screen.
// Each page fetches its API data and dumps it as JSON — replace with the
// real UI (see the comment spec at the top of each page file).
export default function App() {
  return (
    <BrowserRouter>
      <nav style={{ padding: 12, display: "flex", gap: 16 }}>
        <Link to="/">Home</Link>
        <Link to="/loading">Loading</Link>
        <Link to="/dashboard">Dashboard</Link>
        <Link to="/hotspots">Bug Hotspots</Link>
        <Link to="/profile">Developer Profile</Link>
      </nav>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/loading" element={<Loading />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/hotspots" element={<BugHotspots />} />
        <Route path="/profile" element={<DeveloperProfile />} />
      </Routes>
    </BrowserRouter>
  );
}
