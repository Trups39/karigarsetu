r"""Order lifecycle. Every allowed status change lives here, with its audit entry and WhatsApp message.

    awaiting_maker --approve--> approved --> in_production --> ready --> delivered
          |  \--counter--> counter_offered --retailer yes--> approved
          |                       \--retailer no--> rejected
          \--reject--> rejected
"""
import uuid
from datetime import date

from sqlmodel import Session, select

from .. import config, i18n
from ..models import Maker, Order, OrderLine, OrderStatus, Product, Retailer, Stock
from . import audit, feasibility, notify

S = OrderStatus

NEXT_STEP = {S.approved: S.in_production, S.in_production: S.ready, S.ready: S.delivered}
STATUS_TEXT = {
    S.awaiting_maker: "waiting for the maker", S.counter_offered: "waiting for your reply",
    S.approved: "confirmed", S.in_production: "in production", S.ready: "ready to ship",
    S.delivered: "delivered", S.rejected: "cancelled",
}


class OrderError(ValueError):
    """A request that breaks a business rule (wrong status, unknown product, ...)."""


def rupees(n: int) -> str:
    return "₹" + f"{n:,}"


def fmt(d: date | None) -> str:
    return d.strftime("%d %b %Y") if d else "-"


def lines_of(session: Session, order: Order) -> dict[int, int]:
    return {ln.size: ln.qty for ln in session.exec(select(OrderLine).where(OrderLine.order_id == order.id))}


def retailer_language(session: Session, order: Order) -> str:
    """Language for fixed messages to this order's retailer: the order's, else the shop's saved one."""
    if order.language:
        return i18n.norm(order.language)
    r = session.get(Retailer, order.retailer_id) if order.retailer_id else None
    return i18n.norm(r.language if r else "")


def lines_text(lines: dict[int, int]) -> str:
    return ", ".join(f"size {s}: {q}" for s, q in sorted(lines.items()))


def _require(order: Order, *allowed: OrderStatus) -> None:
    if order.status not in allowed:
        raise OrderError(f"Order {order.code} is {order.status.value}; this action needs "
                         + " or ".join(a.value for a in allowed))


def get_by_code(session: Session, code: str, maker_id: int | None = None) -> Order:
    order = session.exec(select(Order).where(Order.code == code.upper())).first()
    if not order or (maker_id is not None and order.maker_id != maker_id):
        raise OrderError(f"Order {code} not found")
    return order


def next_code(session: Session) -> str:
    """KS-1041, KS-1042, ... continuing after the highest existing code (seeded orders included)."""
    numbers = [int(c.split("-")[1]) for c in session.exec(select(Order.code)) if c.startswith("KS-")]
    return f"KS-{max(numbers + [1040]) + 1}"


def upsert_retailer(session: Session, phone: str, name: str, city: str = "", language: str = "") -> Retailer:
    """Find the shop by phone, or add it. Fills in details we didn't have before."""
    r = session.exec(select(Retailer).where(Retailer.phone == phone)).first()
    if not r:
        r = Retailer(name=name, phone=phone, city=city, language=language)
    else:
        r.name = name or r.name
        r.city = city or r.city
        r.language = language or r.language
    session.add(r)
    session.flush()
    return r


# ---------- created by the Sales Agent ----------

def create(session: Session, *, maker_id: int, product_code: str, lines: dict[int, int], retailer_name: str,
           retailer_phone: str, city: str = "", language: str = "", source_text: str = "") -> tuple[Order, feasibility.Feasibility]:
    product = session.exec(select(Product).where(Product.maker_id == maker_id, Product.code == product_code)).first()
    if not product:
        raise OrderError(f"Maker {maker_id} has no product '{product_code}'")
    f = feasibility.check(session, product, lines)
    if f.problems:
        raise OrderError("; ".join(f.problems))
    if f.total == 0:
        raise OrderError("Order has no pairs")

    retailer = upsert_retailer(session, retailer_phone, retailer_name, city, language)
    order = Order(code=f"TMP-{uuid.uuid4().hex[:8]}", maker_id=maker_id, product_id=product.id,
                  retailer_id=retailer.id, retailer_name=retailer_name, retailer_phone=retailer_phone, city=city, language=language,
                  price_per_pair=product.price_per_pair, proposed_date=f.earliest_date)
    session.add(order)
    session.flush()
    order.code = next_code(session)
    for ln in f.lines:
        session.add(OrderLine(order_id=order.id, size=ln.size, qty=ln.qty))

    maker = session.get(Maker, maker_id)
    audit.log(session, "AI agent", "order.drafted",
              f"{product.name}, {f.total} pairs ({lines_text(lines)}) for {retailer_name}"
              + (f" from {language} message: {source_text[:120]}" if source_text else ""),
              maker_id, order.code)
    audit.log(session, "System", "order.feasibility",
              f"{f.ready} ready, {f.to_make} to make, earliest {fmt(f.earliest_date)}", maker_id, order.code)
    ml = maker.language
    notify.send(session, maker.phone, i18n.t(
        "maker_new_order", ml, code=order.code, retailer=retailer_name, city=f", {city}" if city else "",
        product=product.name, total=f.total, lines=i18n.sizes(lines, ml), ready=f.ready, to_make=f.to_make,
        date=i18n.fmt_date(f.earliest_date, ml), price=rupees(product.price_per_pair),
        total_price=rupees(f.total_price)), order.code)
    audit.log(session, "System", "maker.notified", "Approval request sent on WhatsApp", maker_id, order.code)
    session.commit()
    session.refresh(order)
    return order, f


# ---------- maker decisions ----------

def approve(session: Session, order: Order, actor: str = "Maker", due_date: date | None = None) -> Order:
    """Maker approves (optionally with their own delivery date), or retailer accepts a counter-offer."""
    _require(order, S.awaiting_maker, S.counter_offered)
    if due_date is not None:
        if due_date < config.today():
            raise OrderError("Delivery date can't be in the past")
        order.due_date = due_date
    product = session.get(Product, order.product_id)
    lines = lines_of(session, order)
    f = feasibility.check(session, product, lines)   # re-check: stock may have changed since the draft

    for ln in f.lines:   # reserve ready pairs
        st = session.exec(select(Stock).where(Stock.product_id == product.id, Stock.size == ln.size)).first()
        if st and ln.ready:
            st.ready -= ln.ready
            session.add(st)
    order.reserved_ready, order.to_make = f.ready, f.to_make
    if order.due_date is None:
        order.due_date = f.earliest_date
    order.status = S.approved
    session.add(order)

    total = sum(lines.values())
    if actor == "Maker":
        audit.log(session, "Maker", "order.approved",
                  f"{total} pairs at {rupees(order.price_per_pair)}/pair, delivery {fmt(order.due_date)}",
                  order.maker_id, order.code)
    audit.log(session, "System", "stock.reserved",
              f"Reserved {f.ready} ready pairs, booked {f.to_make} for production", order.maker_id, order.code)
    maker = session.get(Maker, order.maker_id)
    rl = retailer_language(session, order)
    notify.send(session, order.retailer_phone, i18n.t(
        "retailer_confirmed", rl, code=order.code, maker=maker.name, product=product.name, total=total,
        total_price=rupees(total * order.price_per_pair), date=i18n.fmt_date(order.due_date, rl)), order.code)
    audit.log(session, "System", "retailer.notified", "Confirmation sent on WhatsApp", order.maker_id, order.code)
    session.commit()
    session.refresh(order)
    return order


def reject(session: Session, order: Order, reason: str = "", actor: str = "Maker") -> Order:
    _require(order, S.awaiting_maker, S.counter_offered)
    order.status = S.rejected
    session.add(order)
    audit.log(session, actor, "order.rejected", reason, order.maker_id, order.code)
    if actor == "Maker":
        maker = session.get(Maker, order.maker_id)
        rl = retailer_language(session, order)
        notify.send(session, order.retailer_phone, i18n.t(
            "retailer_declined", rl, maker=maker.name, code=order.code,
            reason=i18n.t("reason", rl, reason=reason) if reason else ""), order.code)
        audit.log(session, "System", "retailer.notified", "Decline sent on WhatsApp", order.maker_id, order.code)
    session.commit()
    session.refresh(order)
    return order


def counter(session: Session, order: Order, due_date: date | None = None, price_per_pair: int | None = None,
            note: str = "") -> Order:
    _require(order, S.awaiting_maker)
    if due_date is None and price_per_pair is None:
        raise OrderError("Give a new delivery date, a new price, or both")
    if price_per_pair is not None and price_per_pair < 1:
        raise OrderError("Price must be at least ₹1")
    order.due_date = due_date or order.proposed_date
    if price_per_pair is not None:
        order.price_per_pair = price_per_pair
    order.status = S.counter_offered
    session.add(order)
    total = sum(lines_of(session, order).values())
    audit.log(session, "Maker", "order.counter",
              f"{rupees(order.price_per_pair)}/pair, delivery {fmt(order.due_date)}" + (f". {note}" if note else ""),
              order.maker_id, order.code)
    maker = session.get(Maker, order.maker_id)
    rl = retailer_language(session, order)
    notify.send(session, order.retailer_phone, i18n.t(
        "retailer_counter", rl, maker=maker.name, code=order.code, total=total,
        price=rupees(order.price_per_pair), total_price=rupees(total * order.price_per_pair),
        date=i18n.fmt_date(order.due_date, rl), note=i18n.t("note", rl, note=note) if note else ""), order.code)
    audit.log(session, "System", "retailer.notified", "Counter-offer sent on WhatsApp", order.maker_id, order.code)
    session.commit()
    session.refresh(order)
    return order


def retailer_reply(session: Session, order: Order, accept: bool) -> Order:
    _require(order, S.counter_offered)
    audit.log(session, "Retailer", "counter.accepted" if accept else "counter.declined", "", order.maker_id, order.code)
    if accept:
        return approve(session, order, actor="Retailer")
    order = reject(session, order, "Retailer declined the counter-offer", actor="Retailer")
    notify.send(session, order.retailer_phone,
                i18n.t("retailer_cancelled", retailer_language(session, order), code=order.code), order.code)
    session.commit()
    return order


def advance(session: Session, order: Order, to: OrderStatus) -> Order:
    if NEXT_STEP.get(order.status) != to:
        raise OrderError(f"Order {order.code} can't go from {order.status.value} to {to.value}")
    order.status = to
    session.add(order)
    audit.log(session, "Maker", f"order.{to.value}", "", order.maker_id, order.code)
    rl = retailer_language(session, order)
    notify.send(session, order.retailer_phone,
                i18n.t("status_update", rl, code=order.code, status=i18n.status(to.value, rl)), order.code)
    session.commit()
    session.refresh(order)
    return order
