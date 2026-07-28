"""Send the signup verification code — stdlib `smtplib`, no extra dependency.

Two backends behind one `send(msg)` method:

  - `SmtpMailer`    — a real server. Implicit TLS on port 465, STARTTLS on 587.
  - `ConsoleMailer` — prints the code instead of sending it. Chosen
                      automatically when `SMTP_HOST` is empty, so signup works
                      on a laptop with no mail account.

`open_mailer(settings)` picks one; `send_otp()` builds the message and sends it.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

IMPLICIT_TLS_PORT = 465   # 465 is TLS from the first byte; 587 upgrades


class MailError(RuntimeError):
    """A send that failed.

    `bad_address` means the server rejected the recipient — the user mistyped
    their email, rather than our SMTP settings being wrong. The signup route
    uses it to decide whether to throw the pending code away.
    """

    def __init__(self, message: str, bad_address: bool = False):
        super().__init__(message)
        self.bad_address = bad_address


def build_otp_message(from_addr: str, to_addr: str, code: str,
                      ttl_mins: int = 10, app_name: str = "RepoLens") -> EmailMessage:
    """Plain-text + HTML verification mail. The code is in the subject as well,
    so it can be read straight from a phone notification."""
    msg = EmailMessage()
    msg["Subject"] = f"{code} is your {app_name} verification code"
    msg["From"] = formataddr((app_name, from_addr))
    msg["To"] = to_addr
    msg.set_content(
        f"Your {app_name} verification code is:\n\n"
        f"    {code}\n\n"
        f"It expires in {ttl_mins} minutes and can only be used once.\n"
        f"If you didn't try to create an account, you can ignore this email.\n"
    )
    msg.add_alternative(
        f"""<div style="font-family:system-ui,sans-serif;max-width:420px;padding:24px">
  <p>Your <strong>{app_name}</strong> verification code is:</p>
  <p style="font-size:32px;font-weight:700;letter-spacing:6px;font-family:monospace">{code}</p>
  <p style="color:#555;font-size:14px">Expires in {ttl_mins} minutes; usable once.</p>
  <p style="color:#777;font-size:13px">If you didn't try to create an account,
     you can ignore this email.</p>
</div>""",
        subtype="html",
    )
    return msg


_LEVEL_COLOR = {"HIGH": "#c0392b", "MEDIUM": "#b8860b", "LOW": "#2d7a4f"}


def build_pr_review_message(from_addr: str, to_addr: str, report: dict,
                            app_name: str = "RepoLens") -> EmailMessage:
    """Render a Tool 3 report as mail.

    Reads only fields the runner always sets, so a report missing its optional
    LLM summary still produces a complete email.
    """
    repo = report.get("repo") or "?"
    number = report.get("pr")
    spec = f"{repo}#{number}" if number is not None else repo
    level = (report.get("level") or "UNKNOWN").upper()
    warnings = report.get("warnings") or []
    oks = report.get("oks") or []
    url = report.get("url") or ""
    summary = (report.get("summary") or "").strip()
    headline = (f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}"
                if warnings else "no warnings")

    msg = EmailMessage()
    msg["Subject"] = f"[{level}] {spec} — {headline}"
    msg["From"] = formataddr((app_name, from_addr))
    msg["To"] = to_addr
    if url:
        # lets a reply-all thread on the PR rather than at the sender
        msg["X-RepoLens-PR"] = url

    stats = (f"risk {report.get('risk_score', '?')} · "
             f"{report.get('files_changed', '?')} file(s) · "
             f"+{report.get('lines_added', '?')} lines")

    lines = [f"{spec} — risk level {level}", stats, ""]
    if warnings:
        lines += ["Warnings:"] + [f"  - {w}" for w in warnings] + [""]
    if oks:
        lines += ["Looks good:"] + [f"  - {o}" for o in oks] + [""]
    if summary:
        lines += ["Summary:", summary, ""]
    if url:
        lines += [f"Open the PR: {url}", ""]
    lines.append(f"-- {app_name}")
    msg.set_content("\n".join(lines))

    def _ul(items):
        return ("<ul style='margin:0 0 16px;padding-left:20px'>"
                + "".join(f"<li style='margin:4px 0'>{_esc(i)}</li>" for i in items)
                + "</ul>")

    colour = _LEVEL_COLOR.get(level, "#555")
    html = [
        f"<div style=\"font-family:system-ui,sans-serif;max-width:640px;padding:24px\">",
        f"  <p style='margin:0 0 4px'><span style='background:{colour};color:#fff;"
        f"padding:2px 10px;border-radius:3px;font-weight:700;font-size:13px'>"
        f"{level}</span> &nbsp;<strong>{_esc(spec)}</strong></p>",
        f"  <p style='margin:0 0 20px;color:#666;font-size:13px'>{_esc(stats)}</p>",
    ]
    if warnings:
        html.append("  <p style='margin:0 0 6px;font-weight:600'>Warnings</p>")
        html.append(_ul(warnings))
    if oks:
        html.append("  <p style='margin:0 0 6px;font-weight:600'>Looks good</p>")
        html.append(_ul(oks))
    if summary:
        html.append("  <p style='margin:0 0 6px;font-weight:600'>Summary</p>")
        html.append(f"  <p style='margin:0 0 16px;font-size:14px;line-height:1.5'>"
                    f"{_esc(summary)}</p>")
    if url:
        html.append(f"  <p style='margin:0 0 16px'><a href='{_esc(url)}'>"
                    f"Open the pull request</a></p>")
    html.append(f"  <p style='color:#888;font-size:12px;margin:0'>Sent by {app_name}"
                f"</p>\n</div>")
    msg.add_alternative("\n".join(html), subtype="html")
    return msg


def _esc(value) -> str:
    """Report text is remote input (PR titles, file paths, LLM output) and goes
    into an HTML part — escape it rather than trusting it."""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


class SmtpMailer:
    """One connection per send — fine at verification-code volume."""

    backend = "smtp"

    def __init__(self, host: str, port: int = 587, user: str = "",
                 password: str = "", from_addr: str = "", timeout: int = 15):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.from_addr = from_addr or user
        self.timeout = timeout

    def _connect(self):
        if self.port == IMPLICIT_TLS_PORT:
            return smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout,
                                    context=ssl.create_default_context())
        return smtplib.SMTP(self.host, self.port, timeout=self.timeout)

    def send(self, msg: EmailMessage) -> None:
        try:
            with self._connect() as smtp:
                if self.port != IMPLICIT_TLS_PORT:
                    # upgrade BEFORE authenticating, so the password never goes
                    # over a plaintext link (raises if the server can't)
                    smtp.starttls(context=ssl.create_default_context())
                if self.user:
                    smtp.login(self.user, self.password)
                refused = smtp.send_message(msg)
        except smtplib.SMTPAuthenticationError as exc:
            # by far the most common first-run failure, so it gets the fix
            raise MailError(
                f"SMTP rejected the login for {self.user!r}. With Gmail this has "
                f"to be a 16-character App Password (the account needs 2FA), not "
                f"your normal password: {exc}") from exc
        except smtplib.SMTPRecipientsRefused as exc:
            raise MailError(f"the server refused {msg['To']}",
                            bad_address=True) from exc
        except OSError as exc:
            # every smtplib exception, ssl.SSLError, and the socket errors
            # (refused / DNS / timeout) subclass OSError — one clause covers
            # every remaining way a send can fail
            raise MailError(f"could not send via {self.host}:{self.port} — "
                            f"{type(exc).__name__}: {exc}") from exc

        if refused:
            # send_message REPORTS per-address refusals by returning them
            # instead of raising, whenever another recipient was accepted
            raise MailError(f"the server refused {list(refused)}", bad_address=True)


class ConsoleMailer:
    """Prints the message instead of sending it. `sent` lets tests read it back."""

    backend = "console"

    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.sent: list[EmailMessage] = []

    def send(self, msg: EmailMessage) -> None:
        self.sent.append(msg)
        if self.quiet:
            return
        body = msg.get_body(preferencelist=("plain",)).get_content()
        # flush: stdout is block-buffered whenever it isn't a tty (piped to a
        # log, run under a process manager), and a code the developer can't
        # read until the buffer fills is the one thing this backend must not do
        print(f"\n  [mail] to {msg['To']} — {msg['Subject']}\n"
              + "\n".join(f"  | {line}" for line in body.splitlines()),
              flush=True)


def open_mailer(settings):
    """SMTP once host AND credentials are set; console until then.

    Both are required because a host with no login is never a working config —
    leaving SMTP_HOST filled in while the password is still blank would
    otherwise fail every send instead of falling back to the console.

    Never raises: a mail misconfiguration should surface on the one signup it
    breaks, not take the whole API down at startup.
    """
    host = (getattr(settings, "smtp_host", "") or "").strip()
    user = (getattr(settings, "smtp_user", "") or "").strip()
    password = getattr(settings, "smtp_password", "") or ""

    if not (host and user and password):
        missing = [n for n, v in (("SMTP_HOST", host), ("SMTP_USER", user),
                                  ("SMTP_PASSWORD", password)) if not v]
        print(f"  [backend] mail: CONSOLE ({', '.join(missing)} not set — "
              f"verification codes are printed here, not emailed)")
        return ConsoleMailer()

    mailer = SmtpMailer(host, getattr(settings, "smtp_port", 587),
                        user, password,
                        getattr(settings, "smtp_from", "") or "",
                        getattr(settings, "smtp_timeout", 15))
    print(f"  [backend] mail: smtp {host}:{mailer.port} as {mailer.from_addr}")
    return mailer


def send_otp(mailer, settings, to_addr: str, code: str) -> None:
    """Build the verification mail and send it. Raises MailError on failure."""
    mailer.send(build_otp_message(
        from_addr=(getattr(settings, "smtp_from", "")
                   or getattr(settings, "smtp_user", "")
                   or "no-reply@localhost"),
        to_addr=to_addr,
        code=code,
        ttl_mins=getattr(settings, "otp_ttl_mins", 10),
        app_name=getattr(settings, "app_name", "RepoLens"),
    ))
