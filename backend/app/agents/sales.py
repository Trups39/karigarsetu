"""Sales Agent (shops): Claude reads the retailer's WhatsApp message and calls backend tools.

Claude only interprets language and fills in tool arguments. Prices, stock, dates and order creation
all come from the deterministic services, and nothing is promised until the maker approves.
"""

import logging

from sqlmodel import Session, select

from ..core import config
from ..core.models import Maker, Order, Product, Retailer
from ..services import feasibility, orders
from .base import run_agent_loop

log = logging.getLogger("karigarsetu.agent")

SYSTEM = """You are the KarigarSetu order assistant on WhatsApp. Shop owners (retailers) message you to order
Kolhapuri chappals in bulk directly from artisan makers.

Rules:
- Reply in the retailer's language (Marathi, Hindi or English), short and friendly, like a WhatsApp message.
- WhatsApp formatting only: *single stars* for bold, no **double stars**, no # headings, no tables.
- Talk like a helpful shop assistant. Don't explain your reasoning or how you chose the maker or design;
  just say the result (e.g. "Kolhapuri Classic is made by Kolhapur Chappal Kendra, Kolhapur.").
- Never show technical words like tool names, status codes (awaiting_maker) or product codes; use plain words.
- Work out: which maker, which design, how many pairs of each size, the retailer's shop name and city.
  Ask only for what is missing. If the retailer gives a total without sizes, ask for the size split.
- Never choose the maker for the retailer. If they name a maker that isn't in the list below, say so and
  list the makers who sell that design. If more than one maker sells the design and they didn't name one,
  list those makers (name, town, price per pair) and ask which one. Only a maker the retailer chose (or
  the only maker selling that design) may get the order.
- Use list_products to see designs, prices and sizes. Never invent a design, price or size.
- Use check_feasibility before telling the retailer anything about stock or dates.
- Never promise a price, quantity or delivery date as final. Say the maker will confirm.
- Every new request is a new order: call create_order again. Only mention an order number that
  create_order returned in this same reply; never reuse an order number from earlier in the chat.
- When you have everything, summarise the order, then call create_order. Tell the retailer the order
  number and that the maker has been asked to approve it.
- Use get_order_status if they ask about an existing order.

Makers on KarigarSetu:
{makers}

This retailer: {retailer}
"""

TOOLS = [
    {
        "name": "list_products",
        "description": "Designs a maker sells, with price per pair and sizes.",
        "input_schema": {"type": "object", "properties": {"maker_id": {"type": "integer"}}, "required": ["maker_id"]},
    },
    {
        "name": "check_feasibility",
        "description": "How many pairs are ready now, how many must be made, and the earliest delivery date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "maker_id": {"type": "integer"},
                "product_code": {"type": "string"},
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"size": {"type": "integer"}, "qty": {"type": "integer"}},
                        "required": ["size", "qty"],
                    },
                },
            },
            "required": ["maker_id", "product_code", "lines"],
        },
    },
    {
        "name": "create_order",
        "description": "Create the order and send it to the maker for approval. Only call once all details are known.",
        "input_schema": {
            "type": "object",
            "properties": {
                "maker_id": {"type": "integer"},
                "product_code": {"type": "string"},
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"size": {"type": "integer"}, "qty": {"type": "integer"}},
                        "required": ["size", "qty"],
                    },
                },
                "retailer_name": {"type": "string", "description": "Shop name"},
                "city": {"type": "string"},
                "language": {"type": "string", "enum": ["Marathi", "Hindi", "English"]},
                "source_text": {"type": "string", "description": "The retailer's original order message"},
            },
            "required": ["maker_id", "product_code", "lines", "retailer_name", "city", "language"],
        },
    },
    {
        "name": "get_order_status",
        "description": "Status of one of this retailer's orders.",
        "input_schema": {
            "type": "object",
            "properties": {"order_code": {"type": "string"}},
            "required": ["order_code"],
        },
    },
]


def _lines(raw) -> dict[int, int]:
    out: dict[int, int] = {}
    for item in raw or []:
        out[int(item["size"])] = out.get(int(item["size"]), 0) + int(item["qty"])
    return out


def run_tool(session: Session, name: str, args: dict, retailer_phone: str) -> dict:
    """Execute one tool call against the real services. Errors go back to Claude as data."""
    try:
        if name == "list_products":
            ps = session.exec(select(Product).where(Product.maker_id == args["maker_id"]).order_by(Product.id)).all()
            return {
                "products": [
                    {"code": p.code, "name": p.name, "price_per_pair": p.price_per_pair, "sizes": p.size_list()}
                    for p in ps
                ]
            }
        if name == "check_feasibility":
            p = session.exec(
                select(Product).where(Product.maker_id == args["maker_id"], Product.code == args["product_code"])
            ).first()
            if not p:
                return {"error": "Unknown product"}
            return feasibility.check(session, p, _lines(args["lines"])).as_dict()
        if name == "create_order":
            order, f = orders.create(
                session,
                maker_id=args["maker_id"],
                product_code=args["product_code"],
                lines=_lines(args["lines"]),
                retailer_name=args["retailer_name"],
                retailer_phone=retailer_phone,
                city=args.get("city", ""),
                language=args.get("language", ""),
                source_text=args.get("source_text", ""),
            )
            return {"order_code": order.code, "status": "sent to maker for approval", "feasibility": f.as_dict()}
        if name == "get_order_status":
            o = session.exec(
                select(Order).where(Order.code == args["order_code"].upper(), Order.retailer_phone == retailer_phone)
            ).first()
            if not o:
                return {"error": "No such order for this phone number"}
            return {
                "order_code": o.code,
                "status": orders.STATUS_TEXT[o.status],
                "due_date": o.due_date.isoformat() if o.due_date else None,
            }
        return {"error": f"Unknown tool {name}"}
    except orders.OrderError as e:
        session.rollback()
        return {"error": str(e)}


def handle_retailer_message(session: Session, phone: str, text: str) -> str:
    """Sales Agent: retailers ordering on WhatsApp."""
    from ..whatsapp import messages as i18n

    known = session.exec(select(Retailer).where(Retailer.phone == phone)).first()
    lang = i18n.norm(known.language) if known and known.language else i18n.detect(text)
    if not config.ANTHROPIC_API_KEY:
        return i18n.t("retailer_offline", lang)
    makers = session.exec(select(Maker).order_by(Maker.id)).all()
    retailer = (
        f"returning shop {known.name}, {known.city}, prefers {known.language or 'any language'}. "
        "Don't ask for their shop name or city again."
        if known
        else "new; ask for their shop name and city."
    )

    def designs(m):
        ps = session.exec(select(Product).where(Product.maker_id == m.id).order_by(Product.id)).all()
        return ", ".join(f"{p.name} ₹{p.price_per_pair}" for p in ps) or "no designs yet (can't take orders)"

    system = SYSTEM.format(
        makers="\n".join(
            f"- id {m.id}: {m.name}, {m.place}, minimum {m.min_order} pairs. Designs: {designs(m)}" for m in makers
        ),
        retailer=retailer,
    )
    return run_agent_loop(
        session,
        phone,
        text,
        system,
        TOOLS,
        execute=lambda name, args: run_tool(session, name, args, phone),
        give_up=i18n.t("retailer_agent_gave_up", lang),
    )
