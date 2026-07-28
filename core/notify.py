"""Who gets told about a finished PR review, and telling them.

The thin layer between a stored report and `core.mailer`: it knows about
reports and recipients, the mailer knows only about SMTP. Kept out of
`core/mailer.py` so the transport stays free of any notion of accounts.

No configuration of its own — it rides on the SMTP account already set up for
signup codes. With SMTP unset that account is the console backend, so reviews
print instead of sending, exactly like verification codes do.
"""
from __future__ import annotations


def pr_review_recipients(settings, identity, repo_key: str) -> list[str]:
    """Addresses to notify about `repo_key`.

    Multiuser: everyone tracking that repo, which is already exactly the set
    allowed to read the report — so a notification can never surface a repo
    the recipient couldn't open. Otherwise the configured sending address, so
    a single-user setup needs no extra config to get its own reviews.
    """
    if identity is not None:
        try:
            recipients = identity.emails_tracking_repo(repo_key)
        except Exception as exc:  # a lookup failure must not fail the analysis
            print(f"  [warn] could not resolve review recipients: "
                  f"{type(exc).__name__}: {exc}")
            recipients = []
        if recipients:
            return recipients

    own = (getattr(settings, "smtp_from", "")
           or getattr(settings, "smtp_user", "") or "").strip()
    return [own] if own else []


def notify_pr_review(report: dict, settings, identity, mailer) -> int:
    """Email a finished Tool 3 report. Returns how many messages went out.

    Never raises: the report is already saved by the time this runs, and a
    mail problem must not turn a successful review into a failed job.
    """
    if mailer is None or not report:
        return 0
    repo_key = report.get("repo") or ""
    if not repo_key:
        return 0

    recipients = pr_review_recipients(settings, identity, repo_key)
    if not recipients:
        return 0

    from core.mailer import build_pr_review_message

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
        except Exception as exc:  # one bad address must not stop the rest
            print(f"  [warn] review not emailed to {address}: "
                  f"{type(exc).__name__}: {exc}")
    if sent:
        print(f"  [mail] review for {repo_key}#{report.get('pr')} "
              f"sent to {sent} recipient(s)")
    return sent
