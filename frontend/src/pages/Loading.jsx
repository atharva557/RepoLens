/**
 * Analysis-in-progress page  (prototype: ui_protoype/loading.html)
 *
 * Poll the job the Home page started:
 *   GET /jobs/{job_id}      (from the 202 response's status_url)
 *   -> { status: "pending" | "running" | "done" | "failed", result, error }
 *
 * Reality check vs the prototype:
 *   - The backend reports coarse status only — NO step list, NO percentage,
 *     NO time estimate. Render the progress bar as an indeterminate/animated
 *     shimmer and map status to the step copy however you like.
 *   - ABORT_PROCESS has no backend (background tasks can't be cancelled).
 *     Make it just navigate back to Home; the job finishes server-side.
 *
 * On "done"   -> navigate to /dashboard/<repo>.
 * On "failed" -> show job.error (e.g. bad URL, missing GITHUB_TOKEN).
 *
 * Tip: to fill the dashboard completely, fire the other triggers while the
 * user waits (each returns its own job to poll):
 *   POST /commit-quality               body { repo }
 *   POST /repos/{owner/repo}/insights  (needs the LLM running)
 */
import { useEffect, useState } from "react";
import { getJSON } from "../lib/api";

// Plain-text smoke test: open /loading?job=<id> to poll a real job;
// without ?job it shows the /test self-test instead.
export default function Loading() {
  const jobId = new URLSearchParams(window.location.search).get("job");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let timer;
    const tick = () =>
      getJSON(jobId ? `/jobs/${jobId}` : "/test")
        .then((d) => {
          setData(d);
          if (jobId && d.status !== "done" && d.status !== "failed")
            timer = setTimeout(tick, 1500);
        })
        .catch((e) => setError(String(e)));
    tick();
    return () => clearTimeout(timer);
  }, [jobId]);

  if (error) return <pre>API error: {error}</pre>;
  return <pre>{data ? JSON.stringify(data, null, 2) : "loading…"}</pre>;
}
