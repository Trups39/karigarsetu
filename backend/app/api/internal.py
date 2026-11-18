"""Internal endpoints for testing and tools (header X-Internal-Key = INTERNAL_API_KEY).

/internal/simulate-message pretends a WhatsApp message arrived: the same path as a real message,
handy for testing the agents without a phone.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..core.db import get_session
from ..core.models import Product
from ..core.security import clean_phone, internal_only
from ..services import feasibility, orders
from ..whatsapp import router as whatsapp
from .common import Line, RetailerReplyIn, order_view

router = APIRouter(tags=["internal"], dependencies=[Depends(internal_only)])


class FeasibilityIn(BaseModel):
    maker_id: int
    product_code: str
    lines: list[Line]


class OrderIn(FeasibilityIn):
    retailer_name: str
    retailer_phone: str
    city: str = ""
    language: str = ""
    source_text: str = ""


class SimulateIn(BaseModel):
    phone: str
    body: str


@router.post("/internal/feasibility")
def internal_feasibility(body: FeasibilityIn, session: Session = Depends(get_session)):
    p = session.exec(
        select(Product).where(Product.maker_id == body.maker_id, Product.code == body.product_code)
    ).first()
    if not p:
        raise HTTPException(404, "Unknown product")
    return feasibility.check(session, p, {ln.size: ln.qty for ln in body.lines}).as_dict()


@router.post("/internal/orders")
def internal_create_order(body: OrderIn, session: Session = Depends(get_session)):
    lines: dict[int, int] = {}
    for ln in body.lines:
        lines[ln.size] = lines.get(ln.size, 0) + ln.qty
    o, f = orders.create(
        session,
        maker_id=body.maker_id,
        product_code=body.product_code,
        lines=lines,
        retailer_name=body.retailer_name,
        retailer_phone=clean_phone(body.retailer_phone),
        city=body.city,
        language=body.language,
        source_text=body.source_text,
    )
    return {"order": order_view(session, o), "feasibility": f.as_dict()}


@router.post("/internal/orders/{code}/retailer-reply")
def internal_retailer_reply(code: str, body: RetailerReplyIn, session: Session = Depends(get_session)):
    return order_view(session, orders.retailer_reply(session, orders.get_by_code(session, code), body.accept))


@router.post("/internal/simulate-message")
def simulate_message(body: SimulateIn, session: Session = Depends(get_session)):
    """Pretend a WhatsApp message arrived (same handling as a real one)."""
    return {"reply": whatsapp.handle_incoming(session, body.phone, body.body)}
