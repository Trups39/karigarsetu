"""WhatsApp webhook (Meta WhatsApp Cloud API): the only way WhatsApp messages come in.

Every request is checked with HMAC-SHA256 using META_APP_SECRET, repeats are ignored, and the work
(Claude, database, replies) runs in the background because Meta expects a quick 200.
"""

import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlmodel import Session

from ..core import config
from ..core.db import engine
from ..core.security import clean_phone
from ..services import notify
from ..whatsapp import messages as i18n
from ..whatsapp import meta
from ..whatsapp import router as whatsapp

log = logging.getLogger("karigarsetu.webhook")
router = APIRouter()


def _process_meta(items: list) -> None:
    with Session(engine) as session:
        for m in items:
            try:
                if m.text.strip():
                    whatsapp.handle_incoming(session, m.phone, m.text)
                else:  # voice note, photo, sticker...: ask for text
                    phone = clean_phone(m.phone)
                    notify.record_incoming(session, phone, f"[{m.kind} message]")
                    notify.send(session, phone, i18n.t("not_text", whatsapp.language_for(session, phone)))
                    session.commit()
            except Exception:  # one bad message must not stop the others; details are in the log
                session.rollback()
                log.exception("Failed to handle Meta message from %s", m.phone)


@router.get("/webhooks/meta", include_in_schema=False)
def meta_verify(request: Request):
    """Meta calls this once when you click "Verify and save" on the webhook form."""
    q = request.query_params
    if (
        q.get("hub.mode") == "subscribe"
        and config.META_VERIFY_TOKEN
        and hmac.compare_digest(q.get("hub.verify_token", ""), config.META_VERIFY_TOKEN)
    ):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "Verify token doesn't match META_VERIFY_TOKEN in backend/.env")


@router.post("/webhooks/meta", include_in_schema=False)
async def meta_webhook_in(request: Request, background: BackgroundTasks):
    """Every WhatsApp message to the bot number arrives here. We answer Meta at once and
    do the work (Claude, database, replies) in the background, as Meta expects a quick 200."""
    raw = await request.body()
    if not meta.signature_ok(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(403, "Bad signature. Check META_APP_SECRET in backend/.env")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "Not JSON") from None
    items = [m for m in meta.extract_messages(payload) if meta.seen.first_time(m.message_id)]
    if items:
        background.add_task(_process_meta, items)
    return {"ok": True}
