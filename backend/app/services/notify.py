"""Outgoing WhatsApp messages.

Every message is stored in the Message table (so the demo works offline and the dashboard can show it).
It is also sent for real through Meta's WhatsApp Cloud API or Twilio, whichever is set up
(see config.whatsapp_provider).
"""
import logging
import threading
import time

import httpx
from sqlmodel import Session

from .. import config
from ..models import Message

log = logging.getLogger("karigarsetu.notify")

# The Twilio sandbox allows one message every 3 seconds, so sends are spaced out.
MIN_GAP_SECONDS = 3.1
_send_lock = threading.Lock()
_last_send = 0.0


def _twilio_send(phone: str, body: str) -> bool:
    if not (config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN and config.TWILIO_WHATSAPP_FROM):
        return False
    global _last_send
    url = f"https://api.twilio.com/2010-04-01/Accounts/{config.TWILIO_ACCOUNT_SID}/Messages.json"
    with _send_lock:
        wait = MIN_GAP_SECONDS - (time.monotonic() - _last_send)
        if wait > 0:
            time.sleep(wait)
        _last_send = time.monotonic()
    try:
        r = httpx.post(url, auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN), timeout=10,
                       data={"From": config.TWILIO_WHATSAPP_FROM, "To": f"whatsapp:+{phone}", "Body": body})
        r.raise_for_status()
        return True
    except httpx.HTTPError as e:
        log.warning("WhatsApp send to %s failed: %s", phone, e)
        return False


def _meta_send(phone: str, body: str) -> bool:
    """Send a text with Meta's WhatsApp Cloud API.

    Meta only delivers our own text to someone who messaged the bot in the last 24 hours,
    so before a demo every phone should send "hi" once.
    """
    if not (config.META_WHATSAPP_TOKEN and config.META_PHONE_NUMBER_ID):
        return False
    url = f"https://graph.facebook.com/{config.META_GRAPH_VERSION}/{config.META_PHONE_NUMBER_ID}/messages"
    try:
        r = httpx.post(url, timeout=10, headers={"Authorization": f"Bearer {config.META_WHATSAPP_TOKEN}"},
                       json={"messaging_product": "whatsapp", "recipient_type": "individual", "to": phone,
                             "type": "text", "text": {"preview_url": False, "body": body[:4096]}})
        if r.status_code >= 400:
            log.warning("WhatsApp (Meta) send to %s failed: %s %s", phone, r.status_code, r.text[:300])
            return False
        return True
    except httpx.HTTPError as e:
        log.warning("WhatsApp (Meta) send to %s failed: %s", phone, e)
        return False


def _send_now(phone: str, body: str) -> bool:
    provider = config.whatsapp_provider()
    if provider == "meta":
        return _meta_send(phone, body)
    if provider == "twilio":
        return _twilio_send(phone, body)
    return False


def send(session: Session, phone: str, body: str, order_code: str | None = None) -> Message:
    msg = Message(direction="out", phone=phone, body=body, order_code=order_code)
    msg.delivered = _send_now(phone, body)
    session.add(msg)
    return msg


def record_incoming(session: Session, phone: str, body: str) -> None:
    session.add(Message(direction="in", phone=phone, body=body, delivered=True))
