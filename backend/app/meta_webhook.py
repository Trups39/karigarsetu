"""Incoming WhatsApp messages from Meta's WhatsApp Cloud API.

Meta calls our webhook in two ways:
  GET  /webhooks/meta   once, when you click "Verify and save" in Meta. We echo back hub.challenge
                        if hub.verify_token matches META_VERIFY_TOKEN.
  POST /webhooks/meta   for every incoming message (and delivery receipts, which we ignore).
                        Signed with HMAC-SHA256 using the App secret, in the X-Hub-Signature-256 header.
"""
import hashlib
import hmac
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock

from . import config


@dataclass
class Incoming:
    message_id: str
    phone: str          # digits with country code, e.g. 919876543210
    kind: str           # "text", "audio", "image", "button", ...
    text: str           # message text ("" for voice notes, photos, ...)


def signature_ok(raw_body: bytes, header: str | None) -> bool:
    """True if the request really came from Meta. Without an App secret set, checking is skipped."""
    if not config.META_APP_SECRET:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(config.META_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def extract_messages(payload: dict) -> list[Incoming]:
    """Pull the messages out of Meta's nested webhook format. Delivery/read receipts are skipped."""
    out = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for m in value.get("messages", []) or []:
                kind = m.get("type", "")
                if kind == "text":
                    text = (m.get("text") or {}).get("body", "")
                elif kind == "button":                       # quick-reply button on a template
                    text = (m.get("button") or {}).get("text", "")
                elif kind == "interactive":                  # list or button reply
                    inter = m.get("interactive") or {}
                    text = ((inter.get("button_reply") or inter.get("list_reply") or {}).get("title", ""))
                else:
                    text = ""
                out.append(Incoming(m.get("id", ""), m.get("from", ""), kind, text))
    return out


class _SeenIds:
    """Meta can deliver the same message more than once. Remember recent ids and skip repeats."""

    def __init__(self, size: int = 2000):
        self.size, self.ids, self.lock = size, OrderedDict(), Lock()

    def first_time(self, message_id: str) -> bool:
        if not message_id:
            return True
        with self.lock:
            if message_id in self.ids:
                return False
            self.ids[message_id] = True
            if len(self.ids) > self.size:
                self.ids.popitem(last=False)
            return True


seen = _SeenIds()
