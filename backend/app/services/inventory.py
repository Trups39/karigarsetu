"""Maker-side settings: stock, capacity, price, buffer days.

Used by both the dashboard API and the Operations Agent, so the same checks and audit entries apply.
"""
from sqlmodel import Session, select

from ..core.models import Maker, Product, Stock
from . import audit
from .orders import OrderError, rupees


def product(session: Session, maker: Maker, code: str) -> Product:
    p = session.exec(select(Product).where(Product.maker_id == maker.id, Product.code == code)).first()
    if not p:
        codes = ", ".join(x.code for x in session.exec(select(Product).where(Product.maker_id == maker.id)))
        raise OrderError(f"No design '{code}'. Your designs: {codes}")
    return p


def _stock_row(session: Session, p: Product, size: int) -> Stock:
    if size not in p.size_list():
        raise OrderError(f"{p.name} isn't made in size {size} (sizes: {p.sizes})")
    return session.exec(select(Stock).where(Stock.product_id == p.id, Stock.size == size)).first() \
        or Stock(product_id=p.id, size=size, ready=0)


def set_stock(session: Session, maker: Maker, code: str, size: int, ready: int, actor: str = "Maker") -> Stock:
    if ready < 0:
        raise OrderError("Stock can't be negative")
    p = product(session, maker, code)
    row = _stock_row(session, p, size)
    row.ready = ready
    session.add(row)
    audit.log(session, actor, "stock.updated", f"{p.name} size {size} = {ready}", maker.id)
    session.commit()
    session.refresh(row)
    return row


def adjust_stock(session: Session, maker: Maker, code: str, size: int, change: int, actor: str = "Maker") -> Stock:
    """Add (change > 0) or remove (change < 0) ready pairs."""
    p = product(session, maker, code)
    row = _stock_row(session, p, size)
    if row.ready + change < 0:
        raise OrderError(f"Only {row.ready} pairs of {p.name} size {size} in stock, can't remove {-change}")
    return set_stock(session, maker, code, size, row.ready + change, actor)


def set_capacity(session: Session, maker: Maker, code: str, pairs_per_day: int, actor: str = "Maker") -> Product:
    if pairs_per_day < 1:
        raise OrderError("Pairs per day must be at least 1")
    p = product(session, maker, code)
    p.pairs_per_day = pairs_per_day
    session.add(p)
    audit.log(session, actor, "product.updated", f"{p.name}: pairs_per_day = {pairs_per_day}", maker.id)
    session.commit()
    session.refresh(p)
    return p


def set_price(session: Session, maker: Maker, code: str, price_per_pair: int, actor: str = "Maker") -> Product:
    if price_per_pair < 1:
        raise OrderError("Price must be at least ₹1")
    p = product(session, maker, code)
    p.price_per_pair = price_per_pair
    session.add(p)
    audit.log(session, actor, "product.updated", f"{p.name}: price = {rupees(price_per_pair)}", maker.id)
    session.commit()
    session.refresh(p)
    return p


def set_maker_settings(session: Session, maker: Maker, actor: str = "Maker", **changes) -> Maker:
    maker = session.get(Maker, maker.id)
    for key, value in changes.items():
        if value is None:
            continue
        if key == "buffer_days" and value < 0:
            raise OrderError("Buffer days can't be negative")
        if key == "min_order" and value < 1:
            raise OrderError("Minimum order must be at least 1 pair")
        if key == "language":
            from ..whatsapp import messages as i18n
            if value not in i18n.LANGS:
                raise OrderError(f"Language must be one of: {', '.join(i18n.LANGS)}")
        setattr(maker, key, value)
        audit.log(session, actor, "settings.updated", f"{key} = {value}", maker.id)
    session.add(maker)
    session.commit()
    session.refresh(maker)
    return maker
