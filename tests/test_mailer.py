"""Tests for the outbound-mail layer (core/mailer.py).

Network-free: the SMTP backend runs against a fake connection, so the failure
handling is checked without a mail server. That is the part worth testing —
it decides whether a failed send is the deployment's problem or the user's
typo, which is what the signup route branches on.

    python tests/test_mailer.py
"""
import os
import smtplib
import ssl
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.mailer import (
    ConsoleMailer,
    MailError,
    SmtpMailer,
    build_otp_message,
    open_mailer,
    send_otp,
)


class _FakeSMTP:
    """Stands in for smtplib.SMTP/SMTP_SSL as a context manager."""

    def __init__(self, raise_on_send=None, refused=None):
        self.raise_on_send = raise_on_send
        self.refused = refused or {}
        self.calls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        assert context is not None, "STARTTLS must verify certificates"
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append("login")

    def send_message(self, msg):
        self.calls.append("send_message")
        if self.raise_on_send is not None:
            raise self.raise_on_send
        return self.refused


def _mailer(fake, port=587):
    m = SmtpMailer("smtp.example.com", port, "u@example.com", "pw", "u@example.com")
    m._connect = lambda: fake
    return m


def test_otp_message_shape():
    msg = build_otp_message("no-reply@example.com", "user@example.com",
                            "042195", ttl_mins=10, app_name="RepoLens")
    assert msg.is_multipart(), "needs a plain-text part alongside the HTML"
    assert "042195" in msg["Subject"]
    assert msg["From"] == "RepoLens <no-reply@example.com>"
    assert msg["To"] == "user@example.com"

    plain = msg.get_body(preferencelist=("plain",)).get_content()
    html = msg.get_body(preferencelist=("html",)).get_content()
    for part in (plain, html):
        assert "042195" in part      # a leading-zero code stays a string
        assert "10 minutes" in part
    assert "<div" in html and "<div" not in plain
    print("  ok: OTP message is multipart/alternative with the code in both parts")


def test_console_mailer_records_messages():
    mailer = ConsoleMailer(quiet=True)
    assert mailer.backend == "console"
    send_otp(mailer, SimpleNamespace(smtp_from="no-reply@example.com",
                                     otp_ttl_mins=10, app_name="RepoLens"),
             "dev@example.com", "112233")
    assert len(mailer.sent) == 1
    assert "112233" in mailer.sent[0]["Subject"]
    assert mailer.sent[0]["To"] == "dev@example.com"
    print("  ok: console mailer records what it would have sent")


def test_smtp_sends_over_starttls_and_authenticates():
    fake = _FakeSMTP()
    _mailer(fake).send(build_otp_message("a@b.c", "d@e.f", "123456"))
    assert fake.calls == ["starttls", "login", "send_message"]

    # port 465 is already wrapped in TLS — upgrading again would be an error
    fake465 = _FakeSMTP()
    _mailer(fake465, port=465).send(build_otp_message("a@b.c", "d@e.f", "123456"))
    assert fake465.calls == ["login", "send_message"]
    print("  ok: STARTTLS on 587, implicit TLS on 465, always authenticated")


def test_send_failures_become_mailerror():
    """Everything smtplib can throw has to arrive as a MailError, because the
    signup route runs this in a background task that must never raise."""
    msg = build_otp_message("a@b.c", "d@e.f", "123456")
    for exc in [smtplib.SMTPAuthenticationError(535, b"bad creds"),
                smtplib.SMTPNotSupportedError("no STARTTLS"),
                smtplib.SMTPSenderRefused(553, b"bad sender", "a@b.c"),
                smtplib.SMTPServerDisconnected("connection lost"),
                smtplib.SMTPDataError(451, b"greylisted"),
                ConnectionRefusedError("refused"),
                TimeoutError("timed out"),
                ssl.SSLError("handshake failed")]:
        try:
            _mailer(_FakeSMTP(raise_on_send=exc)).send(msg)
        except MailError as err:
            assert not err.bad_address, f"{type(exc).__name__} is not the user's typo"
        else:
            raise AssertionError(f"{type(exc).__name__} should have raised")

    # the App Password hint is the one first-run failure worth spelling out
    try:
        _mailer(_FakeSMTP(raise_on_send=smtplib.SMTPAuthenticationError(
            535, b"bad creds"))).send(msg)
    except MailError as err:
        assert "App Password" in str(err)
    print("  ok: every smtplib failure surfaces as MailError (auth gets a hint)")


def test_refused_recipient_is_flagged_as_the_users_typo():
    """bad_address is what makes the signup route drop the pending code, so a
    mistyped address isn't stuck behind the resend cooldown."""
    msg = build_otp_message("a@b.c", "d@e.f", "123456")

    for fake in (_FakeSMTP(raise_on_send=smtplib.SMTPRecipientsRefused(
                     {"d@e.f": (550, b"no such user")})),
                 # send_message REPORTS per-address refusals by returning them
                 # without raising, whenever another recipient was accepted
                 _FakeSMTP(refused={"d@e.f": (550, b"nope")})):
        try:
            _mailer(fake).send(msg)
        except MailError as err:
            assert err.bad_address
        else:
            raise AssertionError("a refused recipient must raise")
    print("  ok: a refused recipient is flagged bad_address, not a config error")


def test_open_mailer_needs_host_and_credentials():
    base = dict(smtp_port=587, smtp_from="", smtp_timeout=15)
    full = dict(base, smtp_host="smtp.example.com", smtp_user="me@example.com",
                smtp_password="pw")

    # all three present -> real SMTP, From defaulting to the authenticated user
    smtp = open_mailer(SimpleNamespace(**full))
    assert isinstance(smtp, SmtpMailer)
    assert smtp.port == 587 and smtp.from_addr == "me@example.com"

    # any one missing -> console, so a half-filled .env prints codes instead of
    # failing every send
    for missing in ("smtp_host", "smtp_user", "smtp_password"):
        cfg = dict(full)
        cfg[missing] = ""
        assert isinstance(open_mailer(SimpleNamespace(**cfg)), ConsoleMailer), missing
    print("  ok: SMTP needs host+user+password; anything missing falls back to console")


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
