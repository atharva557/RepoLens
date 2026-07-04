/**
 * Developer Profile page  (prototype: ui_protoype/Developer_profile.html)
 * Route suggestion: /profile/:username
 *
 * Everything on this page comes from ONE read:
 *   GET /profiles/{username}
 *   -> {
 *        username, primary_type, label,        // name + type badge
 *        user: {                               // SOCIAL HEADER
 *          name, avatar_url, bio,              //   avatar + bio line
 *          followers, following, public_repos, //   the three counters
 *          years_active, created_at, url },    //   "Years Active" stat
 *        commits_analyzed,                     // Total Commits stat *
 *        prs_merged,                           // PRs Merged stat
 *        authored_prs,                         //   (authored, if you want it)
 *        issues_resolved,                      // Issues Resolved stat
 *        heatmap: [{ date, count }],           // ANNUAL VELOCITY grid
 *                                              //   (non-zero days only — pad)
 *        languages: [{ name, pct }],           // TOP LANGUAGES donut
 *        activity_split: { "Feature Builder": 44, ... },  // CONTRIBUTION MIX
 *        commit_message_quality,               // COMMIT HEALTH gauge (0-10,
 *                                              //   prototype shows /100: x10)
 *        review_participation, reviews,
 *        llm_summary                           // optional AI blurb (or null)
 *      }
 *
 *   * commits_analyzed is capped by PROFILE_MAX_REPOS/…_COMMITS_PER_REPO —
 *     label it "commits analyzed", not lifetime commits.
 *
 * On 404 ("no profile for X"):
 *   POST /profiles/{username}   -> 202 + job (needs GITHUB_TOKEN server-side;
 *   a 400 means the token isn't configured). Poll the job, then re-fetch.
 *   POST always rebuilds fresh, so use it for a "refresh profile" button too.
 *
 * Gauge sub-stats: "Semantic %" has no direct field — derive from
 *   commit_message_quality or drop; "Avg Char" is on the REPO quality report
 *   (avg_subject_len), not the profile.
 * Follow / mail buttons: decorative only — no backend.
 */
import { useEffect, useState } from "react";
import { getJSON } from "../lib/api";

// Plain-text smoke test. Change user via /profile?user=<github-login>
const DEFAULT_USER = "atharva557";

export default function DeveloperProfile() {
  const user = new URLSearchParams(window.location.search).get("user") || DEFAULT_USER;
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getJSON(`/profiles/${user}`)
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [user]);

  if (error) return <pre>API error: {error}</pre>;
  return <pre>{data ? JSON.stringify(data, null, 2) : "loading…"}</pre>;
}
