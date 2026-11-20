"""Maker dashboard API (needs a logged-in maker: Authorization: Bearer <token>).

Each maker only ever sees and changes their own orders, designs and stock.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, func, select

from ..core.db import get_session
from ..core.models import AuditLog, Maker, Message, Order, OrderStatus, Product, Retailer, Stock
from ..core.security import current_maker
from ..services import feasibility, inventory, orders
from ..services import validation as V
from .common import order_view

router = APIRouter(tags=["maker dashboard"])


class RejectIn(BaseModel):
    reason: str = ""


class CounterIn(BaseModel):
    due_date: Optional[date] = None
    price_per_pair: Optional[int] = Field(default=None, gt=0)
    note: str = ""


class AdvanceIn(BaseModel):
    to: OrderStatus


class StockIn(BaseModel):
    product_code: str
    size: int
    ready: int = Field(ge=0)


class ProductIn(BaseModel):
    name: str = ""
    price_per_pair: float | int | str | None = None  # checked in add_product (friendly messages)
    pairs_per_day: float | int | str | None = 5
    sizes: str = "6,7,8,9,10"


class ProductPatch(BaseModel):
    price_per_pair: Optional[int] = Field(default=None, gt=0)
    pairs_per_day: Optional[int] = Field(default=None, gt=0)


class MakerPatch(BaseModel):
    buffer_days: Optional[int] = Field(default=None, ge=0)
    min_order: Optional[int] = Field(default=None, ge=1)
    language: Optional[str] = None  # Marathi, Hindi or English


@router.get("/api/me")
def me(maker: Maker = Depends(current_maker)):
    return maker


@router.patch("/api/me")
def update_me(body: MakerPatch, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    return inventory.set_maker_settings(session, maker, **body.model_dump(exclude_none=True))


@router.get("/api/overview")
def overview(maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    pids = [p.id for p in session.exec(select(Product).where(Product.maker_id == maker.id).order_by(Product.id))]
    ready = session.exec(select(func.coalesce(func.sum(Stock.ready), 0)).where(Stock.product_id.in_(pids))).one()
    mine = select(Order).where(Order.maker_id == maker.id)
    count = lambda *st: len(session.exec(mine.where(Order.status.in_(st))).all())  # noqa: E731
    in_prod = sum(
        o.to_make for o in session.exec(mine.where(Order.status.in_([OrderStatus.approved, OrderStatus.in_production])))
    )
    return {
        "pairs_ready": int(ready),
        "pairs_in_production": in_prod,
        "awaiting_approval": count(OrderStatus.awaiting_maker),
        "upcoming_deliveries": count(OrderStatus.approved, OrderStatus.in_production, OrderStatus.ready),
        "recent_activity": session.exec(
            select(AuditLog)
            .where(AuditLog.maker_id == maker.id)
            .order_by(AuditLog.ts.desc(), AuditLog.id.desc())
            .limit(8)
        ).all(),
    }


@router.get("/api/orders")
def list_orders(
    status: Optional[OrderStatus] = None, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)
):
    q = select(Order).where(Order.maker_id == maker.id)
    if status:
        q = q.where(Order.status == status)
    return [order_view(session, o) for o in session.exec(q.order_by(Order.created_at.desc(), Order.id.desc()))]


@router.get("/api/orders/{code}")
def get_order(code: str, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    return order_view(session, orders.get_by_code(session, code, maker.id), detail=True)


@router.post("/api/orders/{code}/approve")
def approve(code: str, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    return order_view(session, orders.approve(session, orders.get_by_code(session, code, maker.id)))


@router.post("/api/orders/{code}/reject")
def reject(code: str, body: RejectIn, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    return order_view(session, orders.reject(session, orders.get_by_code(session, code, maker.id), body.reason))


@router.post("/api/orders/{code}/counter")
def counter(code: str, body: CounterIn, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    o = orders.get_by_code(session, code, maker.id)
    return order_view(session, orders.counter(session, o, body.due_date, body.price_per_pair, body.note))


@router.post("/api/orders/{code}/advance")
def advance(code: str, body: AdvanceIn, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    return order_view(session, orders.advance(session, orders.get_by_code(session, code, maker.id), body.to))


@router.get("/api/products")
def products(maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    out = []
    for p in session.exec(select(Product).where(Product.maker_id == maker.id).order_by(Product.id)):
        out.append({**p.model_dump(), "committed": feasibility.committed_pairs(session, p.id)})
    return out


@router.post("/api/products", status_code=201)
def add_product(body: ProductIn, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    """A maker adds a design they sell (same rules as on WhatsApp). Stock starts at 0 for every size."""
    # Field problems -> 400 with the message for the form; a duplicate name -> 409.
    V.design_name(body.name)
    V.whole_number(body.price_per_pair, "Price per pair", 1, 100000)
    V.whole_number(body.pairs_per_day, "Pairs per day", 1, 1000)
    V.sizes(body.sizes)
    try:
        p = inventory.add_product(session, maker, body.name, body.price_per_pair, body.pairs_per_day, body.sizes)
    except orders.OrderError as e:
        raise HTTPException(409, str(e)) from None
    return {**p.model_dump(), "committed": 0}


@router.patch("/api/products/{code}")
def update_product(
    code: str, body: ProductPatch, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)
):
    p = inventory.product(session, maker, code)
    if body.price_per_pair is not None:
        p = inventory.set_price(session, maker, code, body.price_per_pair)
    if body.pairs_per_day is not None:
        p = inventory.set_capacity(session, maker, code, body.pairs_per_day)
    return p


@router.get("/api/stock")
def stock(maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    out = []
    for p in session.exec(select(Product).where(Product.maker_id == maker.id).order_by(Product.id)):
        rows = {s.size: s.ready for s in session.exec(select(Stock).where(Stock.product_id == p.id))}
        out.append(
            {
                "product_code": p.code,
                "product_name": p.name,
                "sizes": {sz: rows.get(sz, 0) for sz in p.size_list()},
                "total": sum(rows.values()),
            }
        )
    return out


@router.put("/api/stock")
def set_stock(body: StockIn, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    row = inventory.set_stock(session, maker, body.product_code, body.size, body.ready)
    return {"product_code": body.product_code, "size": body.size, "ready": row.ready}


@router.get("/api/retailers")
def retailers(maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    """Shops that have ordered from this maker, with their order count and total pairs."""
    out = []
    for r in session.exec(select(Retailer).order_by(Retailer.name)):
        mine = session.exec(select(Order).where(Order.maker_id == maker.id, Order.retailer_id == r.id)).all()
        if mine:
            out.append(
                {
                    **r.model_dump(),
                    "orders": len(mine),
                    "pairs": sum(sum(orders.lines_of(session, o).values()) for o in mine),
                }
            )
    return out


@router.get("/api/audit")
def audit_log(limit: int = 100, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    return session.exec(
        select(AuditLog)
        .where(AuditLog.maker_id == maker.id)
        .order_by(AuditLog.ts.desc(), AuditLog.id.desc())
        .limit(min(limit, 500))
    ).all()


@router.get("/api/messages")
def messages(limit: int = 50, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    """WhatsApp messages linked to this maker's orders (also shown when WhatsApp sending is off)."""
    codes = [o.code for o in session.exec(select(Order).where(Order.maker_id == maker.id))]
    return session.exec(
        select(Message)
        .where(Message.order_code.in_(codes))
        .order_by(Message.ts.desc(), Message.id.desc())
        .limit(min(limit, 200))
    ).all()
