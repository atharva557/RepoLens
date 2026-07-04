/**
 * Bug Hotspots page  (prototype: ui_protoype/Bughotspot.html)
 * Route suggestion: /hotspots/:owner/:repo
 *
 * MAIN TABLE (rank / file / risk level / risk score):
 *   GET /repos/{key}/hotspots?top=200
 *   -> { repo, generated_at, rows: [
 *          { path,                       // File Name
 *            score,                      // 0..1 — render as score*100
 *            components: { bug, churn, authors, complexity },  // weighted parts
 *            raw: { ...unnormalized numbers... },
 *            reasons: [string],          // plain-English "why"
 *            ml_prob }                   // XGBoost 2nd opinion or null
 *      ] }
 *   Rows arrive sorted by risk. Rank = index+1.
 *   Risk Level chip: derive client-side, e.g. score >= .7 Critical,
 *   >= .4 High, else Medium. 404 -> "not analyzed yet", offer POST /analyze.
 *
 * KEY RISK METRICS cards: compute from rows client-side
 *   (count above threshold, average score). "Code Coverage Impact" has NO
 *   backend — remove that card (GitPulse/RepoLens does no coverage analysis).
 *
 * DEEP METRICS side panel (click a row -> selected file):
 *   All numbers are already in the clicked row — no extra request:
 *     Cyclomatic Complexity <- row.raw complexity/loc value
 *     Change Frequency      <- row.raw churn value
 *     plus row.reasons for the explanation lines.
 *   "Risk Trend (30d)" chart: NOT supported — the store keeps only the
 *     latest snapshot (no history). Drop the chart and trend arrows.
 *   "AI Recommendations" per file: NOT supported (insights are repo-level:
 *     GET /repos/{key}/insights). Reuse those or drop the block.
 *   "Recent Risky Changes": no per-file endpoint; nearest real data is
 *     GET /repos/{key}/activity recent_commits (repo-wide, has is_bugfix).
 *   "Generate Refactor Plan" button: no backend — remove.
 *
 * Search + Filter + pagination: client-side over the fetched rows.
 */
import { useEffect, useState } from "react";
import { getJSON } from "../lib/api";

// Plain-text smoke test. Change repo via /hotspots?repo=owner/name
const DEFAULT_REPO = "expressjs/express";

export default function BugHotspots() {
  const repo = new URLSearchParams(window.location.search).get("repo") || DEFAULT_REPO;
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getJSON(`/repos/${repo}/hotspots?top=20`)
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [repo]);

  if (error) return <pre>API error: {error}</pre>;
  return <pre>{data ? JSON.stringify(data, null, 2) : "loading…"}</pre>;
}
