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
- Quote first, order second. When you have everything, call check_feasibility and send the retailer a
  short quote: maker, design, pairs per size, how many are ready now and how many must be made, price
  per pair, total, and the earliest delivery date. End with: reply YES to send it to the maker, NO to
  cancel, or tell me what to change (sizes, quantity, delivery date, or the price you'd like).
  Then stop and wait: never call create_order in the same reply as the quote.
- Call create_order only after the retailer answers that quote with a yes (yes, ok, हो, होय, हां, ठीक है).
  If they asked for a different price or delivery date, still use the quote but put their wish in
  retailer_request; tell them the maker will decide (the price stays the list price until the maker agrees).
  If they change sizes, quantity or design, check feasibility again and send a new quote.
  If they say no, don't create anything and tell them they can order again any time.
- Every new request is a new order. Only mention an order number that create_order returned in this
  same reply; never reuse an order number from earlier in the chat.
- After create_order, tell the retailer the order number and that the maker has been asked to approve it.
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
        "description": (
            "Create the order and send it to the maker for approval. Only after the retailer said yes to the "
            "quote you sent in an earlier message, with exactly the same maker, design and sizes."
        ),
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
                "retailer_request": {
                    "type": "string",
                    "description": "Optional: a different price or delivery date the retailer asked for, in plain words",
                },
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


# Quotes the retailer has seen: phone -> (maker_id, product_code, sizes) and the message number it was sent in.
# create_order is only allowed for a quote sent in an EARLIER message, so the shop always gets to say YES first.
_quotes: dict[str, tuple[tuple, int]] = {}
_turns: dict[str, int] = {}

NEEDS_YES = (
    "Not created. First send the retailer the quote (pairs per size, ready vs to make, price, total, earliest "
    "date) and ask them to reply YES. Create the order only when they answer yes in their next message."
)


def _quote_key(args: dict) -> tuple:
    return (int(args["maker_id"]), str(args["product_code"]), tuple(sorted(_lines(args["lines"]).items())))


def _lines(raw) -> dict[int, int]:
    out: dict[int, int] = {}
    for item in raw or []:
        out[int(item["size"])] = out.get(int(item["size"]), 0) + int(item["qty"])
    return out


def run_tool(session: Session, name: str, args: dict, retailer_phone: str, turn: int = 0) -> dict:
    """Execute one tool call against the real services. Errors go back to Claude as data.
    turn = the number of this retailer message (see _quotes)."""
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
            f = feasibility.check(session, p, _lines(args["lines"]))
            if not f.problems and f.total:
                _quotes[retailer_phone] = (_quote_key(args), turn)
            return f.as_dict()
        if name == "create_order":
            quote = _quotes.get(retailer_phone)
            if not quote or quote[0] != _quote_key(args) or quote[1] >= turn:
                return {"error": NEEDS_YES}
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
                retailer_request=args.get("retailer_request", ""),
            )
            _quotes.pop(retailer_phone, None)
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

    _turns[phone] = turn = _turns.get(phone, 0) + 1
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
        execute=lambda name, args: run_tool(session, name, args, phone, turn),
        give_up=i18n.t("retailer_agent_gave_up", lang),
    )
