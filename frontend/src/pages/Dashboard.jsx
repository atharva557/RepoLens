/**
 * Repo dashboard  (prototype: ui_protoype/Dashboard(1).html)
 * Route suggestion: /dashboard/:owner/:repo  -> key = `${owner}/${repo}`
 *
 * HEADER (name, description, Public badge, stars, forks, language):
 *   GET /repos/{key}/meta        (add ?refresh=true behind a manual refresh)
 *   -> { full_name, description, language,
 *        languages: [{ name, pct }], stars, forks, open_issues,
 *        visibility, default_branch, url, generated_at }
 *   "OPEN ON GITHUB" button -> meta.url
 *   404 here just means no GITHUB_TOKEN / local-only repo — hide the badges.
 *
 * STATS ROW + HEATMAP + TOP CONTRIBUTORS + RECENT COMMITS:
 *   GET /repos/{key}/activity?days=365&recent=15
 *   -> { total_commits, window_days, window_commits, window_bugfix_ratio,
 *        contributors_total,                       // CONTRIBUTORS stat card
 *        contributors: [{ author, commits, share }],   // TOP CONTRIBUTORS
 *        recent_commits: [{ sha, subject, author, date, is_bugfix }],
 *        heatmap: [{ date: "YYYY-MM-DD", count }], // CONTRIBUTIONS grid
 *        health: { score, commit_quality, stability, formula } }  // HEALTH card
 *   Heatmap: only non-zero days are listed — fill the other cells with 0.
 *   OPEN ISSUES stat card comes from meta.open_issues (above).
 *
 * AI INSIGHTS card:
 *   GET /repos/{key}/insights
 *   -> { bullets: [string], provider, generated_at }
 *   On 404: POST /repos/{key}/insights (202 + job), poll, re-fetch.
 *   Requires the LLM (LM Studio) to be up — on failed job, show a quiet
 *   "insights unavailable" state, never block the page.
 *
 * COMMIT QUALITY card:
 *   GET /repos/{key}/commit-quality
 *   -> { avg_score (0-10), good, weak, commits,
 *        pct_imperative,      // "Conventional Commits" row
 *        pct_referenced,      // "Link to Issues" row
 *        avg_subject_len,     // "Avg. Message Length" row
 *        contributors, trend, common_issues, worst }
 *   On 404: POST /commit-quality  body { repo: key } -> job -> re-fetch.
 *
 * LANGUAGES card: meta.languages (see above) — name + pct, render bars.
 *
 * RE-ANALYZE button:
 *   POST /analyze  body { repo: key, refresh: true } -> Loading-page flow.
 *
 * Settings drawer is pure client-side (localStorage) — no API.
 * Search bar (⌘K): filter the GET /repos list client-side.
 */
import { useEffect, useState } from "react";
import { getJSON } from "../lib/api";

// Plain-text smoke test for one repo key. Change via /dashboard?repo=owner/name
const DEFAULT_REPO = "expressjs/express";

export default function Dashboard() {
  const repo = new URLSearchParams(window.location.search).get("repo") || DEFAULT_REPO;
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const soft = (p) => getJSON(p).catch((e) => ({ unavailable: String(e) }));
    Promise.all([
      getJSON(`/repos/${repo}/activity?recent=5`),
      soft(`/repos/${repo}/meta`),
      soft(`/repos/${repo}/commit-quality`),
      soft(`/repos/${repo}/insights`),
    ])
      .then(([activity, meta, quality, insights]) =>
        setData({ repo, activity, meta, quality, insights }))
      .catch((e) => setError(String(e)));
  }, [repo]);

  if (error) return <pre>API error: {error}</pre>;
  return <pre>{data ? JSON.stringify(data, null, 2) : "loading…"}</pre>;
}
