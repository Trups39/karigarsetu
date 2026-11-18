"""Public endpoints: health check, the makers shown on the home page, and contact details."""

from urllib.parse import quote

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..core import config
from ..core.db import get_session
from ..core.models import AccountStatus, Maker, Product, SupplierAccount

router = APIRouter(tags=["public"])


@router.get("/health")
def health():
    return {"ok": True, "today": config.today()}


@router.get("/public/makers")
def public_makers(session: Session = Depends(get_session)):
    """Makers shown on the home page: approved (or sample) suppliers that have at least one design.
    "Order on WhatsApp" opens a chat with the KarigarSetu bot, with the maker's name already typed."""
    out = []
    for m in session.exec(select(Maker).order_by(Maker.id)).all():
        acc = session.exec(select(SupplierAccount).where(SupplierAccount.maker_id == m.id)).first()
        if acc and acc.status != AccountStatus.approved:
            continue
        ps = session.exec(select(Product).where(Product.maker_id == m.id).order_by(Product.id)).all()
        if not ps:
            continue
        text = f"Hi, I want to place a bulk order with {m.name} via KarigarSetu"
        number = config.BOT_WHATSAPP_NUMBER or m.phone
        out.append(
            {
                "id": m.id,
                "name": m.name,
                "place": m.place,
                "min_order": m.min_order,
                "whatsapp": f"https://wa.me/{number}?text={quote(text)}",
                "designs": [{"name": p.name, "price_per_pair": p.price_per_pair} for p in ps],
                "price_from": min(p.price_per_pair for p in ps),
                "pairs_per_day": sum(p.pairs_per_day for p in ps),
            }
        )
    return out


@router.get("/public/info")
def public_info():
    """Contact details shown on the website."""
    return {"email": config.CONTACT_TO, "whatsapp": config.BOT_WHATSAPP_NUMBER}
