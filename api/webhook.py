"""GitHub PR webhook (v0.4) — the piece deferred from v0.3.

Verifies the `X-Hub-Signature-256` HMAC against GITHUB_WEBHOOK_SECRET and, for
pull_request events that open/update a PR, triggers Tool 3 in the background.
The report is always persisted to the store; posting it back to the PR as a
comment is opt-in via GITPULSE_WEBHOOK_POST (default off — outward-facing).

Pure stdlib except for the Tool 3 runner it dispatches to.
"""
from __future__ import annotations

import hashlib
import hmac

from tools.pr_reviewer.runner import run_pr_review

# PR lifecycle actions that warrant a (re-)review
REVIEW_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Check GitHub's sha256 HMAC header against the raw request body."""
    if not secret or not signature_header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def pr_spec_from_payload(payload: dict) -> str | None:
    """Extract 'owner/repo#number' from a pull_request event payload."""
    pr = payload.get("pull_request") or {}
    repo = (payload.get("repository") or {}).get("full_name")
    number = pr.get("number")
    if not repo or not number:
        return None
    return f"{repo}#{number}"


def review_pr_from_payload(payload: dict, settings, store, identity=None,
                           mailer=None, progress=None) -> dict:
    """Run Tool 3 for the PR in the payload (background-task entry point).

    Two opt-in delivery channels hang off the finished report: a comment on
    the PR (GITPULSE_WEBHOOK_POST) and email to whoever tracks the repo
    (PR_REVIEW_EMAIL). Both default off; the report is persisted either way.
    """
    spec = pr_spec_from_payload(payload)
    if spec is None:
        raise ValueError("payload has no repository/pull_request number")
    report = run_pr_review(spec, settings, store,
                           post=settings.webhook_post_comment, progress=progress)

    from core.notify import notify_pr_review

    emailed = notify_pr_review(report, settings, identity, mailer)
    # keep the job result small — the full report is in the store
    return {
        "pr": spec,
        "level": report.get("level"),
        "warnings": report.get("warnings"),
        "posted": report.get("posted"),
        "emailed": emailed,
    }
