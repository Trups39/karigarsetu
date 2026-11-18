"""Send email through the Titan mailbox on our GoDaddy domain (contact form, new-supplier alerts).

Settings in backend/.env (the password is never in the code or the repo):
    SMTP_HOST=smtp.titan.email   SMTP_PORT=465   SMTP_USERNAME=contact@karigarsetu.co.in   SMTP_PASSWORD=...
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from .. import config

log = logging.getLogger("karigarsetu.mail")


class MailNotConfigured(RuntimeError):
    pass


def configured() -> bool:
    return bool(config.SMTP_USERNAME and config.SMTP_PASSWORD)


def send_mail(subject: str, body: str, to: str | None = None, reply_to: str | None = None) -> None:
    """Send one plain-text email. Raises MailNotConfigured or smtplib/OSError errors."""
    if not configured():
        raise MailNotConfigured("SMTP_USERNAME / SMTP_PASSWORD are not set in backend/.env")
    msg = EmailMessage()
    msg["From"] = formataddr(("KarigarSetu", config.SMTP_USERNAME))
    msg["To"] = to or config.CONTACT_TO
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=config.SMTP_USERNAME.split("@")[-1])
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    context = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context, timeout=20) as smtp:
            smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            smtp.starttls(context=context)
            smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            smtp.send_message(msg)


def send_quietly(subject: str, body: str, to: str | None = None, reply_to: str | None = None) -> bool:
    """For background alerts: never raises, logs the problem instead."""
    try:
        send_mail(subject, body, to=to, reply_to=reply_to)
        return True
    except MailNotConfigured:
        log.warning("Email not sent (SMTP not set up): %s", subject)
    except Exception:  # noqa: BLE001
        log.exception("Email not sent: %s", subject)
    return False
