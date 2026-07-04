/**
 * Home / landing page  (prototype: ui_protoype/github_url.html)
 *
 * "Analyze" button (paste a GitHub URL):
 *   POST /analyze
 *   body: { repo: "<pasted URL or owner/repo or local path>",
 *           refresh: false, top: 15 }
 *   -> 202 { job_id, status_url } — navigate to the Loading page and poll.
 *
 * "// RECENT ANALYSES" list:
 *   GET /repos
 *   -> { repos: [ { repo, commits,
 *                   hotspots: { generated_at, files } | null,
 *                   commit_quality: { generated_at } | null,
 *                   pr_reviews: [numbers] } ] }
 *   Use hotspots.generated_at for the "analyzed 2h ago" label; sort by it
 *   client-side. Each row links to /dashboard/<repo>.
 *
 * The example chips (facebook/react etc.) just prefill the input.
 * Footer "SYSTEM_READY" light: GET /health (status === "ok").
 */
import { useEffect, useState } from "react";
import { getJSON } from "../lib/api";

// Plain-text smoke test: shows /health + the /repos discovery list.
export default function Home() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([getJSON("/health"), getJSON("/repos")])
      .then(([health, repos]) => setData({ health, repos }))
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <pre>API error: {error}</pre>;
  return <pre>{data ? JSON.stringify(data, null, 2) : "loading…"}</pre>;
}
