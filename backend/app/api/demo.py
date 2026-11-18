"""Dashboard demo buttons ("Simulate new WhatsApp order", "Simulate retailer accepts"). Off when DEMO_MODE=false."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from ..core import config
from ..core.db import get_session
from ..core.models import Maker, Order, Product, Retailer
from ..core.security import current_maker
from ..services import orders
from .common import RetailerReplyIn, order_view

DEMO_RETAILERS = [
    ("Kolhapur Footwear Mart", "Kolhapur", "Marathi", "919811110001"),
    ("Mumbai Craft Co.", "Mumbai", "English", "919811110002"),
    ("Indore Juti Ghar", "Indore", "Hindi", "919811110003"),
    ("Satara Chappal Bazaar", "Satara", "Marathi", "919811110004"),
]


def demo_only():
    if not config.DEMO_MODE:
        raise HTTPException(404, "Not found")


router = APIRouter(tags=["demo"], dependencies=[Depends(demo_only)])


@router.post("/api/demo/simulate-order")
def demo_simulate_order(maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    """Creates a sample order as if the Sales Agent had drafted it from a WhatsApp message."""
    n = session.exec(select(func.count()).select_from(Order).where(Order.maker_id == maker.id)).one()
    products_ = session.exec(select(Product).where(Product.maker_id == maker.id).order_by(Product.id)).all()
    if not products_:
        raise HTTPException(409, "Add your designs first (Products), then simulate an order.")
    pune = session.exec(select(Retailer).where(Retailer.name == "Pune Footwear House")).first()
    pune_phone = pune.phone if pune else "919811112222"
    pune_done = session.exec(
        select(Order).where(Order.maker_id == maker.id, Order.retailer_phone == pune_phone)
    ).first()
    if not pune_done:  # the first one is the demo story: a Pune shop orders 50 pairs
        name, city, lang, phone = "Pune Footwear House", "Pune", "Marathi", pune_phone
        p = next((x for x in products_ if x.code == "classic"), products_[0])
        lines = {7: 15, 8: 20, 9: 15}
    else:
        name, city, lang, phone = DEMO_RETAILERS[n % len(DEMO_RETAILERS)]
        p = products_[n % len(products_)]
        sizes = p.size_list()[1:4]
        lines = {sizes[0]: 6 + (n % 5) * 2, sizes[1]: 10 + (n % 3) * 4, sizes[2]: 6 + (n % 4) * 2}
    if sum(lines.values()) < maker.min_order:
        lines[sizes[1]] += maker.min_order - sum(lines.values())
    o, _ = orders.create(
        session,
        maker_id=maker.id,
        product_code=p.code,
        lines=lines,
        retailer_name=name,
        retailer_phone=phone,
        city=city,
        language=lang,
        source_text="(simulated WhatsApp order)",
    )
    return order_view(session, o)


@router.post("/api/demo/orders/{code}/retailer-reply")
def demo_retailer_reply(
    code: str, body: RetailerReplyIn, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)
):
    return order_view(session, orders.retailer_reply(session, orders.get_by_code(session, code, maker.id), body.accept))
