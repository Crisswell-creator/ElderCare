"""Email transports and the branded template.

`smtp` works with any SMTP provider (Gmail/Google Workspace with an app password, SendGrid,
Mailgun...). `console` logs a redacted line for local development; `memory` keeps messages
in a list for tests. "Sent" means the server accepted the message; inbox delivery is not
observable over SMTP, and the app never claims it.
"""

from __future__ import annotations

import html
import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage

from app.config import get_settings
from app.logging_setup import log_event

logger = logging.getLogger("eldercare.email")


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str


@dataclass
class MemoryOutbox:
    messages: list[OutgoingEmail] = field(default_factory=list)
    fail_next: int = 0  # tests set this to simulate provider failures


memory_outbox = MemoryOutbox()


class EmailError(Exception):
    pass


def render(
    *, heading: str, paragraphs: list[str], action_label: str = "", action_url: str = ""
) -> tuple[str, str]:
    """Returns (text, html). Content is escaped; the layout is a single readable column."""
    footer = (
        "You receive this because you are part of an ElderCare care circle. "
        "You can change email preferences in ElderCare under Account."
    )
    text_parts = [heading, "", *paragraphs]
    if action_url:
        text_parts += ["", f"{action_label}: {action_url}"]
    text_parts += ["", "--", footer]

    body = "".join(
        f'<p style="margin:0 0 16px;font-size:17px;line-height:1.55;color:#1d2b36">{html.escape(p)}</p>'
        for p in paragraphs
    )
    button = (
        f'<p style="margin:24px 0"><a href="{html.escape(action_url, quote=True)}" '
        'style="background:#0b5c58;color:#ffffff;text-decoration:none;padding:12px 20px;'
        f'border-radius:6px;font-weight:600;font-size:16px;display:inline-block">{html.escape(action_label)}</a></p>'
        if action_url
        else ""
    )
    page = f"""<!doctype html><html lang="en"><body style="margin:0;background:#f3f5f4;padding:24px;font-family:Arial,Helvetica,sans-serif">
<table role="presentation" width="100%" style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #d6ddda;border-radius:8px">
<tr><td style="padding:20px 28px;border-bottom:1px solid #e3e8e6;font-weight:700;font-size:18px;color:#102a43">ElderCare</td></tr>
<tr><td style="padding:28px">
<h1 style="margin:0 0 16px;font-size:22px;color:#102a43">{html.escape(heading)}</h1>
{body}{button}
</td></tr>
<tr><td style="padding:16px 28px;border-top:1px solid #e3e8e6;font-size:13px;line-height:1.5;color:#52616b">{html.escape(footer)}</td></tr>
</table></body></html>"""
    return "\n".join(text_parts), page


def send(message: OutgoingEmail) -> None:
    settings = get_settings()
    transport = settings.email_transport
    if transport == "memory":
        if memory_outbox.fail_next > 0:
            memory_outbox.fail_next -= 1
            raise EmailError("simulated provider failure")
        memory_outbox.messages.append(message)
        return
    if transport == "console":
        # Never log bodies: they can carry links with single-use tokens.
        log_event(
            logger,
            logging.INFO,
            "email (console transport)",
            to=message.to,
            subject=message.subject,
        )
        return

    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = message.to
    msg["Subject"] = message.subject
    msg.set_content(message.text)
    msg.add_alternative(message.html, subtype="html")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailError(f"{type(exc).__name__}: {exc}") from exc


def send_now(
    to: str,
    subject: str,
    *,
    heading: str,
    paragraphs: list[str],
    action_label: str = "",
    action_url: str = "",
) -> bool:
    """Direct send for account-security mail whose links must not be stored in the outbox.
    Returns False instead of raising so auth flows never reveal provider failures."""
    text, page = render(
        heading=heading, paragraphs=paragraphs, action_label=action_label, action_url=action_url
    )
    try:
        send(OutgoingEmail(to=to, subject=subject, text=text, html=page))
        return True
    except EmailError as exc:
        log_event(logger, logging.ERROR, "security email failed", subject=subject, error=str(exc))
        return False
