"""Stock + production feasibility. Plain arithmetic: the AI never decides these numbers."""
import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlmodel import Session, func, select

from ..core import config
from ..core.models import ACTIVE_PRODUCTION, Maker, Order, Product, Stock


@dataclass
class SizeLine:
    size: int
    qty: int
    in_stock: int
    ready: int
    to_make: int


@dataclass
class Feasibility:
    product_code: str
    product_name: str
    total: int
    ready: int
    to_make: int
    pairs_per_day: int
    already_committed: int
    buffer_days: int
    days_needed: int
    earliest_date: date
    price_per_pair: int
    total_price: int
    lines: list[SizeLine] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["earliest_date"] = self.earliest_date.isoformat()
        d["lines"] = [line.__dict__ for line in self.lines]
        return d


def committed_pairs(session: Session, product_id: int) -> int:
    """Pairs already booked into production by approved, unfinished orders."""
    q = select(func.coalesce(func.sum(Order.to_make), 0)).where(
        Order.product_id == product_id, Order.status.in_(ACTIVE_PRODUCTION)
    )
    return int(session.exec(q).one())


def check(session: Session, product: Product, lines: dict[int, int], start: date | None = None) -> Feasibility:
    """lines = {size: qty}. Returns ready vs to-make split and the earliest delivery date."""
    maker = session.get(Maker, product.maker_id)
    start = start or config.today()
    stock = {s.size: s.ready for s in session.exec(select(Stock).where(Stock.product_id == product.id))}
    valid_sizes = set(product.size_list())

    out_lines, problems = [], []
    ready_total = make_total = 0
    for size, qty in sorted(lines.items()):
        size, qty = int(size), int(qty)
        if qty <= 0:
            continue
        if size not in valid_sizes:
            problems.append(f"Size {size} is not made for {product.name} (sizes: {product.sizes})")
            continue
        have = stock.get(size, 0)
        r = min(have, qty)
        out_lines.append(SizeLine(size, qty, have, r, qty - r))
        ready_total += r
        make_total += qty - r

    total = ready_total + make_total
    if total and total < maker.min_order:
        problems.append(f"Minimum order for {maker.name} is {maker.min_order} pairs")

    committed = committed_pairs(session, product.id)
    if make_total > 0:
        days = math.ceil((committed + make_total) / max(product.pairs_per_day, 1)) + maker.buffer_days
    else:
        days = 1  # ready stock: pack and dispatch next day

    return Feasibility(
        product_code=product.code, product_name=product.name, total=total,
        ready=ready_total, to_make=make_total, pairs_per_day=product.pairs_per_day,
        already_committed=committed, buffer_days=maker.buffer_days, days_needed=days,
        earliest_date=start + timedelta(days=days), price_per_pair=product.price_per_pair,
        total_price=total * product.price_per_pair, lines=out_lines, problems=problems,
    )
