"""Pieces shared by the order endpoints: request bodies used in several places, and the order view."""
from sqlmodel import Session, select
from pydantic import BaseModel, Field

from ..core.models import AuditLog, Message, Order, OrderStatus, Product
from ..services import feasibility, orders


class Line(BaseModel):
    size: int
    qty: int = Field(gt=0)


class RetailerReplyIn(BaseModel):
    accept: bool


def order_view(session: Session, o: Order, detail: bool = False) -> dict:
    p = session.get(Product, o.product_id)
    lines = orders.lines_of(session, o)
    total = sum(lines.values())
    d = {"code": o.code, "status": o.status, "retailer_name": o.retailer_name, "retailer_phone": o.retailer_phone,
         "city": o.city, "language": o.language, "product_code": p.code, "product_name": p.name,
         "lines": [{"size": s, "qty": q} for s, q in sorted(lines.items())], "total_pairs": total,
         "price_per_pair": o.price_per_pair, "total_price": total * o.price_per_pair,
         "proposed_date": o.proposed_date, "due_date": o.due_date, "reserved_ready": o.reserved_ready,
         "to_make": o.to_make, "created_at": o.created_at}
    if detail:
        if o.status in (OrderStatus.awaiting_maker, OrderStatus.counter_offered):
            d["feasibility"] = feasibility.check(session, p, lines).as_dict()
        d["audit"] = session.exec(select(AuditLog).where(AuditLog.order_code == o.code).order_by(AuditLog.ts)).all()
        d["messages"] = session.exec(select(Message).where(Message.order_code == o.code).order_by(Message.ts)).all()
    return d
