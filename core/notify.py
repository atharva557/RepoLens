"""Who gets told about a finished analysis, and telling them.

The thin layer between a stored report and `core.mailer`: it knows about
reports and recipients, the mailer knows only about SMTP. Kept out of
`core/mailer.py` so the transport stays free of any notion of accounts.

Outward-facing and therefore **opt-in** — `PR_REVIEW_EMAIL=false` by default,
the same stance `GITPULSE_WEBHOOK_POST` takes on posting PR comments. A tool
that silently emails people the first time a webhook fires is a tool nobody
installs twice.
"""
from __future__ import annotations


def pr_review_recipients(settings, identity, repo_key: str) -> list[str]:
    """Addresses to notify about `repo_key`.

    Multiuser: everyone tracking that repo (`user_repos`), which is exactly
    the set already allowed to read the report — so notification can never
    reveal a repo the recipient couldn't already open.

    Single-user: there are no accounts, so NOTIFY_EMAIL is the only address.
    Unset means nothing is sent, which is the correct default for a feature
    that reaches outside the machine.
    """
    fallback = (getattr(settings, "notify_email", "") or "").strip()
    if identity is None:
        return [fallback] if fallback else []

    try:
        recipients = identity.emails_tracking_repo(repo_key)
    except Exception as exc:  # a lookup failure must not fail the analysis
        print(f"  [warn] could not resolve notification recipients: "
              f"{type(exc).__name__}: {exc}")
        return []
    # NOTIFY_EMAIL still applies in multiuser mode — an operator address that
    # wants every review regardless of who tracks the repo
    if fallback and fallback not in recipients:
        recipients = [*recipients, fallback]
    return recipients


def notify_pr_review(report: dict, settings, identity, mailer) -> int:
    """Email a finished Tool 3 report. Returns how many messages went out.

    Never raises: this runs after the report is already saved, and a mail
    problem must not turn a successful review into a failed job.
    """
    if not getattr(settings, "pr_review_email", False):
        return 0
    if mailer is None or not report:
        return 0

    repo_key = report.get("repo") or ""
    if not repo_key:
        return 0

    recipients = pr_review_recipients(settings, identity, repo_key)
    if not recipients:
        return 0

    from core.mailer import MailError, build_pr_review_message

    from_addr = (getattr(settings, "smtp_from", "")
                 or getattr(settings, "smtp_user", "")
                 or "no-reply@localhost")
    app_name = getattr(settings, "app_name", "RepoLens")

    sent = 0
    for address in recipients:
        try:
            mailer.send(build_pr_review_message(from_addr, address, report,
                                                app_name))
            sent += 1
        except MailError as exc:
            # one bad address must not stop the rest of the list
            print(f"  [warn] PR review not emailed to {address}: {exc}")
        except Exception as exc:
            print(f"  [warn] PR review not emailed to {address}: "
                  f"{type(exc).__name__}: {exc}")
    if sent:
        print(f"  [mail] PR review for {report.get('repo')}#{report.get('pr')} "
              f"sent to {sent} recipient(s)")
    return sent
