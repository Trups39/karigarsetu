"""Routes an incoming WhatsApp message.

- From a maker: quick replies "1" approve, "2" reject, "3" change (optionally with an order code;
  "3 KS-1042 2026-12-01 600" proposes a date and/or price). Anything else goes to the Operations Agent.
- From a retailer with a pending counter-offer: YES / NO (also हो, नाही, हां, नहीं).
- Anything else from a retailer goes to the Sales Agent.
"""

import re
from datetime import date

from sqlmodel import Session, select

from ..agents import operations, sales
from ..core.models import Maker, Order, OrderStatus, Retailer
from ..core.security import clean_phone, find_maker
from ..services import audit, notify, orders
from . import messages as i18n

YES = {"yes", "y", "ok", "haan", "ha", "हो", "होय", "हां", "हाँ", "हा"}
NO = {"no", "n", "nahi", "nako", "नाही", "नहीं", "नको"}
CODE = re.compile(r"\bKS-\d+\b", re.I)


def _pending_for_maker(session: Session, maker: Maker, code: str | None) -> Order | None:
    q = select(Order).where(Order.maker_id == maker.id, Order.status == OrderStatus.awaiting_maker)
    if code:
        q = q.where(Order.code == code.upper())
    return session.exec(q.order_by(Order.created_at)).first()


def _maker_reply(session: Session, maker: Maker, text: str) -> str:
    parts = text.strip().split()
    cmd = parts[0] if parts else ""
    m = CODE.search(text)
    order = _pending_for_maker(session, maker, m.group(0) if m else None)
    if cmd not in {"1", "2", "3"}:  # anything else: the Operations Agent understands normal sentences
        return operations.handle_maker_message(session, maker, text)
    lang = maker.language
    if not order:
        return i18n.t("maker_nothing_pending", lang)
    try:
        if cmd == "1":
            orders.approve(session, order)
            return i18n.t("maker_approved", lang, code=order.code, date=i18n.fmt_date(order.due_date, lang))
        if cmd == "2":
            orders.reject(session, order)
            return i18n.t("maker_rejected", lang, code=order.code)
        new_date = next((date.fromisoformat(p) for p in parts if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p)), None)
        new_price = next((int(p) for p in parts[1:] if p.isdigit()), None)
        if not (new_date or new_price):
            return i18n.t("maker_change_help", lang, code=order.code)
        orders.counter(session, order, due_date=new_date, price_per_pair=new_price)
        return i18n.t("maker_counter_sent", lang, code=order.code)
    except orders.OrderError as e:
        session.rollback()
        return str(e)


def language_for(session: Session, phone: str, text: str = "") -> str:
    """Language for fixed messages to this phone: the maker's or shop's saved one, else a guess from the text."""
    maker = find_maker(session, phone)
    if maker:
        return i18n.norm(maker.language)
    shop = session.exec(select(Retailer).where(Retailer.phone == clean_phone(phone))).first()
    if shop and shop.language:
        return i18n.norm(shop.language)
    return i18n.detect(text)


def handle_incoming(session: Session, raw_phone: str, text: str) -> str:
    """Returns the reply text (also stored and sent via notify)."""
    phone = clean_phone(raw_phone)
    notify.record_incoming(session, phone, text)

    maker = find_maker(session, phone)
    if maker:
        audit.log(session, "Maker", "whatsapp.in", text[:200], maker.id)
        reply = _maker_reply(session, maker, text)
    else:
        word = text.strip().lower().strip("!. ")
        counter = session.exec(
            select(Order)
            .where(Order.retailer_phone == phone, Order.status == OrderStatus.counter_offered)
            .order_by(Order.created_at.desc())
        ).first()
        if counter and word in YES | NO:
            orders.retailer_reply(session, counter, accept=word in YES)
            session.commit()
            return ""  # retailer_reply already sent the confirmation or cancellation
        reply = sales.handle_retailer_message(session, phone, text)

    notify.send(session, phone, reply)
    session.commit()
    return reply
