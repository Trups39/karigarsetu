"""Public contact form -> contact@karigarsetu.co.in through the Titan mailbox (GoDaddy email).

Every message is also saved in the contact_message table, so nothing is lost if email is down.
Spam protection: a hidden "website" field (bots fill it in), basic checks, and a limit per address.
"""
import logging
import re
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from . import config
from .db import get_session
from .models import ContactMessage
from .services import mailer

log = logging.getLogger("karigarsetu.contact")
router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LIMIT, WINDOW = 5, 3600          # at most 5 messages per hour from one address
_recent: dict[str, list[float]] = {}


class ContactIn(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    message: str = ""
    website: str = ""            # honeypot: hidden on the page, people leave it empty


def _rate_ok(key: str) -> bool:
    now = time.time()
    hits = [t for t in _recent.get(key, []) if now - t < WINDOW]
    _recent[key] = hits
    if len(hits) >= LIMIT:
        return False
    hits.append(now)
    return True


@router.post("/api/contact", tags=["public"])
def contact(body: ContactIn, request: Request, session: Session = Depends(get_session)):
    if body.website.strip():                       # a bot filled in the hidden field: pretend it worked
        return {"ok": True, "message": "Thank you! We'll get back to you soon."}
    name = " ".join(body.name.split())
    email = body.email.strip().lower()
    phone = re.sub(r"[^\d+ ]", "", body.phone)[:20]
    text = body.message.strip()
    if not 2 <= len(name) <= 100:
        raise HTTPException(400, "Please enter your name.")
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(400, "Please enter a valid email address.")
    if not 10 <= len(text) <= 3000:
        raise HTTPException(400, "Please write a message (at least 10 characters).")
    if not _rate_ok(request.client.host if request.client else "?"):
        raise HTTPException(429, "Too many messages. Please try again in an hour.")

    row = ContactMessage(name=name, email=email, phone=phone, message=text)
    session.add(row)
    session.commit()

    subject = f"KarigarSetu contact form: {name}"
    body_text = (f"New message from the KarigarSetu website contact form.\n\n"
                 f"Name:  {name}\nEmail: {email}\nPhone: {phone or '-'}\n\n{text}\n")
    try:
        mailer.send_mail(subject, body_text, reply_to=email)
        log.info("Contact form from %s emailed to %s", email, config.CONTACT_TO)
        row.emailed = True
        session.add(row)
        session.commit()
    except mailer.MailNotConfigured:
        log.warning("Contact form saved but not emailed: SMTP is not set up in backend/.env")
    except Exception:  # noqa: BLE001
        log.exception("Contact form saved but the email failed")
        raise HTTPException(502, f"Sorry, we couldn't send your message right now. "
                                 f"Please email us at {config.CONTACT_TO}.")
    return {"ok": True, "message": "Thank you! We'll get back to you soon."}


def reset_limits(_: Optional[str] = None) -> None:
    """For tests."""
    _recent.clear()
