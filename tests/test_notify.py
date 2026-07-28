"""Tests for PR-review notification (core/notify.py + the mailer's renderer).

Network-free: a ConsoleMailer stands in for SMTP and MemoryIdentity for the
accounts table, so the interesting parts — who gets told, and whether anyone
gets told at all — are exercised without either.

    python tests/test_notify.py
"""
import os
import sys
from importlib.util import find_spec
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.mailer import ConsoleMailer, MailError, build_pr_review_message
from core.notify import notify_pr_review, pr_review_recipients

REPORT = {
    "repo": "owner/repo", "pr": 42, "level": "HIGH", "risk_score": 0.8,
    "files_changed": 19, "lines_added": 3806,
    "url": "https://github.com/owner/repo/pull/42",
    "warnings": ["touches high-risk file(s): src/auth.py",
                 "large diff (+3806 lines)"],
    "oks": ["tests updated (5 file(s))"],
    "summary": "Adds an MCP server for GPU resources.",
}


def _settings(**over):
    # no config of its own — it rides on the SMTP account set up for signup
    base = dict(smtp_from="bot@example.com", smtp_user="", app_name="RepoLens")
    return SimpleNamespace(**{**base, **over})


def test_pr_review_message_shape():
    msg = build_pr_review_message("bot@example.com", "dev@example.com", REPORT)
    assert msg.is_multipart()
    # the subject alone should say whether this needs attention
    assert msg["Subject"] == "[HIGH] owner/repo#42 — 2 warnings"
    assert msg["To"] == "dev@example.com"
    assert msg["From"] == "RepoLens <bot@example.com>"

    plain = msg.get_body(preferencelist=("plain",)).get_content()
    html = msg.get_body(preferencelist=("html",)).get_content()
    for part in (plain, html):
        assert "owner/repo#42" in part
        assert "src/auth.py" in part               # warnings carried over
        assert "tests updated (5 file(s))" in part  # and the oks
        assert "MCP server" in part                 # and the LLM summary
        assert "pull/42" in part                    # link back to the PR
    print("  ok: PR review renders to text + HTML with warnings, oks and summary")


def test_singular_plural_and_missing_fields():
    one = build_pr_review_message("a@b.c", "d@e.f", {**REPORT, "warnings": ["x"]})
    assert one["Subject"].endswith("1 warning")          # not "1 warnings"
    none = build_pr_review_message("a@b.c", "d@e.f", {**REPORT, "warnings": []})
    assert none["Subject"].endswith("no warnings")

    # a report with no LLM summary and no url must still render completely
    bare = {"repo": "owner/repo", "pr": 7, "level": "LOW"}
    msg = build_pr_review_message("a@b.c", "d@e.f", bare)
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "owner/repo#7" in body and "LOW" in body
    print("  ok: singular/plural subject, and a bare report still renders")


def test_report_text_is_escaped_in_the_html_part():
    """Warnings carry file paths and LLM output — remote input landing in an
    HTML part, so it gets escaped rather than trusted."""
    nasty = {**REPORT, "warnings": ["<script>alert(1)</script> in a<b.py"]}
    html = build_pr_review_message("a@b.c", "d@e.f", nasty).get_body(
        preferencelist=("html",)).get_content()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html and "a&lt;b.py" in html
    print("  ok: report text is HTML-escaped, not injected")


def test_single_user_falls_back_to_the_sending_account():
    """No identity plane means no accounts to look up, so the review goes to
    the address already configured for sending — no extra .env entry."""
    mailer = ConsoleMailer(quiet=True)
    assert notify_pr_review(REPORT, _settings(), None, mailer) == 1
    assert mailer.sent[-1]["To"] == "bot@example.com"

    # SMTP_FROM is usually blank, in which case SMTP_USER is the account
    mailer2 = ConsoleMailer(quiet=True)
    assert notify_pr_review(REPORT, _settings(smtp_from="", smtp_user="me@gmail.com"),
                            None, mailer2) == 1
    assert mailer2.sent[-1]["To"] == "me@gmail.com"

    # nothing configured at all -> nothing sent, rather than a crash
    assert notify_pr_review(REPORT, _settings(smtp_from="", smtp_user=""),
                            None, ConsoleMailer(quiet=True)) == 0
    # and a report with no repo key is a no-op
    assert notify_pr_review({}, _settings(), None, ConsoleMailer(quiet=True)) == 0
    print("  ok: single-user falls back to the configured sending account")


def test_recipients_are_the_users_tracking_the_repo():
    if find_spec("cryptography") is None:  # pragma: no cover
        print("  skip: cryptography not installed")
        return
    from cryptography.fernet import Fernet

    from core.identity import MemoryIdentity

    ident = MemoryIdentity(Fernet.generate_key().decode())
    alice = ident.create_password_user("alice@example.com", "h")
    bob = ident.create_password_user("bob@example.com", "h")
    ident.create_password_user("carol@example.com", "h")   # tracks nothing
    ident.track_repo(alice["id"], "owner/repo")
    ident.track_repo(bob["id"], "owner/repo")
    ident.track_repo(alice["id"], "other/repo")

    # exactly the people who track it — which is exactly who may already read
    # the report, so notifying can't leak a repo they couldn't open.
    # Sets, not lists: emails_tracking_repo deliberately promises no order
    # (Postgres collation and Python's sorted() disagree).
    assert set(pr_review_recipients(_settings(), ident, "owner/repo")) == {
        "alice@example.com", "bob@example.com"}
    assert set(pr_review_recipients(_settings(), ident, "other/repo")) == {
        "alice@example.com"}

    # a repo nobody tracks still reaches the operator, via the sending account
    assert pr_review_recipients(_settings(), ident, "nobody/repo") == [
        "bot@example.com"]

    mailer = ConsoleMailer(quiet=True)
    assert notify_pr_review(REPORT, _settings(), ident, mailer) == 2
    assert sorted(m["To"] for m in mailer.sent) == ["alice@example.com",
                                                    "bob@example.com"]
    print("  ok: recipients are the repo's trackers, else the sending account")


def test_one_bad_address_does_not_stop_the_rest():
    """This runs after the report is saved, so a mail failure must never turn
    a successful review into a failed job."""
    class HalfBroken(ConsoleMailer):
        def send(self, msg):
            if msg["To"] == "broken@example.com":
                raise MailError("refused", bad_address=True)
            super().send(msg)

    class Ident:
        def emails_tracking_repo(self, key):
            return ["broken@example.com", "ok@example.com"]

    mailer = HalfBroken(quiet=True)
    assert notify_pr_review(REPORT, _settings(), Ident(), mailer) == 1
    assert [m["To"] for m in mailer.sent] == ["ok@example.com"]

    # a store that cannot answer at all is survivable too: the lookup is
    # logged and we fall back to the sending account, so the review still
    # reaches the operator rather than vanishing
    class Exploding:
        def emails_tracking_repo(self, key):
            raise RuntimeError("db down")

    fallback = ConsoleMailer(quiet=True)
    assert notify_pr_review(REPORT, _settings(), Exploding(), fallback) == 1
    assert fallback.sent[-1]["To"] == "bot@example.com"
    print("  ok: a refused address or a dead lookup never fails the review")


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
