"""Operations Agent: makers manage orders, stock and capacity on WhatsApp in their own words.

Examples: "आज किती ऑर्डर बाकी आहेत?", "Size 8 Classic 10 jodi add kar",
"KS-1042 approve kar, pan delivery 5 December".

Every tool is limited to this maker's own data and calls the same services as the dashboard,
so the order rules, stock checks and audit log apply exactly as they do there.
"""

import json
from datetime import date

from sqlmodel import Session, select

from ..core import config
from ..core.models import Maker, Order, OrderStatus, Product, Stock
from ..services import audit, feasibility, inventory, orders
from ..whatsapp import messages as i18n
from .base import run_agent_loop

SYSTEM = """You are the operations assistant for {maker} ({place}) on KarigarSetu, on WhatsApp.
The maker uses you to manage bulk orders from retailers, ready stock and production capacity.
Today is {today}.

Rules:
- Reply in the maker's language (Marathi, Hindi, English or a mix), short, like a WhatsApp message.
  If the message is too short to tell (e.g. "approve kar", "ok", "1"), reply in {language}.
- WhatsApp formatting only: *single stars* for bold, no **double stars**, no # headings, no tables.
- Never show technical words like tool names or status codes (awaiting_maker, in_production); say them plainly
  (e.g. "मंजुरीची वाट", "तयार होत आहे"). Order codes like KS-1041 are fine.
- Don't explain your reasoning; just say what you found or did.
- In Marathi say "जोड्या" for pairs (one pair = "जोडी").
- Always check with the tools first (list_orders / get_order). Never rely on what was said earlier in the chat:
  orders, stock and statuses may have changed since.
- Only do what the maker clearly asked. If it's unclear which order, design, size or date they mean, ask first.
- When the maker states an order's new stage ("KS-1041 production madhe ahe", "ready ahe", "delivered zali") and
  that move is allowed now, do it straight away with update_order_status; don't ask them to confirm. If it isn't
  allowed yet (e.g. still waiting for approval), say so and offer the right next step.
- earliest_possible_date is the system's estimate from stock and capacity. It is not a date the retailer asked
  for; never say the retailer suggested it. due_date is the agreed delivery date (after approval or a change).
- Use the tools for every fact and every change. Never guess stock, dates or prices.
- If the maker asks for automatic messages in another language, use set_message_language.
- Dates: turn "5 December" or "पुढच्या सोमवारी" into YYYY-MM-DD, using today's date. Assume the next upcoming date.
- Approving with a different delivery date is fine. A different price is a change the retailer must accept:
  use propose_change, not approve_order.
- After a change, confirm in one line what was done (and say the retailer was notified, if they were).
- If a tool returns an error, explain it simply and suggest what to do.

This maker's designs (code: name):
{designs}
"""

_order_code = {"type": "string", "description": "Order code like KS-1042"}
_product = {"type": "string", "description": "Design code, e.g. classic"}

TOOLS = [
    {
        "name": "list_orders",
        "description": "This maker's orders, newest first. Filter by status if useful.",
        "input_schema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": [s.value for s in OrderStatus]}},
        },
    },
    {
        "name": "get_order",
        "description": "Full details of one order, with ready vs to-make if it's still pending.",
        "input_schema": {"type": "object", "properties": {"order_code": _order_code}, "required": ["order_code"]},
    },
    {
        "name": "approve_order",
        "description": "Approve a pending order. Optionally set the delivery date (YYYY-MM-DD).",
        "input_schema": {
            "type": "object",
            "properties": {"order_code": _order_code, "due_date": {"type": "string", "format": "date"}},
            "required": ["order_code"],
        },
    },
    {
        "name": "reject_order",
        "description": "Reject a pending order. The retailer is told politely.",
        "input_schema": {
            "type": "object",
            "properties": {"order_code": _order_code, "reason": {"type": "string"}},
            "required": ["order_code"],
        },
    },
    {
        "name": "propose_change",
        "description": "Send the retailer a counter-offer: new delivery date and/or price per pair.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_code": _order_code,
                "due_date": {"type": "string", "format": "date"},
                "price_per_pair": {"type": "integer"},
                "note": {"type": "string"},
            },
            "required": ["order_code"],
        },
    },
    {
        "name": "update_order_status",
        "description": "Move an approved order forward: in_production, ready, delivered.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_code": _order_code,
                "to": {"type": "string", "enum": ["in_production", "ready", "delivered"]},
            },
            "required": ["order_code", "to"],
        },
    },
    {
        "name": "get_stock",
        "description": "Ready pairs by size, for one design or all.",
        "input_schema": {"type": "object", "properties": {"product_code": _product}},
    },
    {
        "name": "adjust_stock",
        "description": "Add (positive) or remove (negative) ready pairs of one design and size.",
        "input_schema": {
            "type": "object",
            "properties": {"product_code": _product, "size": {"type": "integer"}, "change": {"type": "integer"}},
            "required": ["product_code", "size", "change"],
        },
    },
    {
        "name": "set_stock",
        "description": "Set ready pairs of one design and size to an exact number.",
        "input_schema": {
            "type": "object",
            "properties": {"product_code": _product, "size": {"type": "integer"}, "ready": {"type": "integer"}},
            "required": ["product_code", "size", "ready"],
        },
    },
    {
        "name": "set_capacity",
        "description": "How many pairs of a design the workshop can make per day.",
        "input_schema": {
            "type": "object",
            "properties": {"product_code": _product, "pairs_per_day": {"type": "integer"}},
            "required": ["product_code", "pairs_per_day"],
        },
    },
    {
        "name": "set_price",
        "description": "Price per pair for a design (applies to new orders).",
        "input_schema": {
            "type": "object",
            "properties": {"product_code": _product, "price_per_pair": {"type": "integer"}},
            "required": ["product_code", "price_per_pair"],
        },
    },
    {
        "name": "set_message_language",
        "description": "Language of the automatic WhatsApp messages this maker gets (order alerts, confirmations).",
        "input_schema": {
            "type": "object",
            "properties": {"language": {"type": "string", "enum": list(i18n.LANGS)}},
            "required": ["language"],
        },
    },
    {
        "name": "set_buffer_days",
        "description": "Extra days added to every delivery estimate (leather, drying, holidays).",
        "input_schema": {"type": "object", "properties": {"days": {"type": "integer"}}, "required": ["days"]},
    },
]

WRITE_TOOLS = {
    "approve_order",
    "reject_order",
    "propose_change",
    "update_order_status",
    "adjust_stock",
    "set_stock",
    "set_capacity",
    "set_price",
    "set_buffer_days",
    "set_message_language",
}


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _order_summary(session: Session, o: Order) -> dict:
    p = session.get(Product, o.product_id)
    lines = orders.lines_of(session, o)
    return {
        "code": o.code,
        "status": o.status.value,
        "retailer": o.retailer_name,
        "city": o.city,
        "design": p.name,
        "pairs": sum(lines.values()),
        "sizes": lines,
        "price_per_pair": o.price_per_pair,
        "earliest_possible_date": o.proposed_date,
        "due_date": o.due_date,
    }


def run_tool(session: Session, maker: Maker, name: str, args: dict, message: str) -> dict:
    try:
        if name in WRITE_TOOLS:  # record what the agent did and why, before doing it
            audit.log(
                session,
                "Ops agent",
                "agent.action",
                f"{name} {json.dumps(args, ensure_ascii=False)} for message: {message[:100]}",
                maker.id,
                args.get("order_code", "").upper() or None,
            )

        if name == "list_orders":
            q = select(Order).where(Order.maker_id == maker.id)
            if args.get("status"):
                q = q.where(Order.status == OrderStatus(args["status"]))
            return {
                "orders": [
                    _order_summary(session, o)
                    for o in session.exec(q.order_by(Order.created_at.desc(), Order.id.desc()).limit(20))
                ]
            }
        if name == "get_order":
            o = orders.get_by_code(session, args["order_code"], maker.id)
            out = _order_summary(session, o)
            if o.status in (OrderStatus.awaiting_maker, OrderStatus.counter_offered):
                out["feasibility"] = feasibility.check(
                    session, session.get(Product, o.product_id), orders.lines_of(session, o)
                ).as_dict()
            return out
        if name == "approve_order":
            o = orders.approve(
                session, orders.get_by_code(session, args["order_code"], maker.id), due_date=_date(args.get("due_date"))
            )
            return {"done": True, "retailer_notified": True, **_order_summary(session, o)}
        if name == "reject_order":
            o = orders.reject(
                session, orders.get_by_code(session, args["order_code"], maker.id), args.get("reason", "")
            )
            return {"done": True, "retailer_notified": True, **_order_summary(session, o)}
        if name == "propose_change":
            o = orders.counter(
                session,
                orders.get_by_code(session, args["order_code"], maker.id),
                _date(args.get("due_date")),
                args.get("price_per_pair"),
                args.get("note", ""),
            )
            return {"done": True, "retailer_notified": True, "waiting_for_retailer": True, **_order_summary(session, o)}
        if name == "update_order_status":
            o = orders.advance(
                session, orders.get_by_code(session, args["order_code"], maker.id), OrderStatus(args["to"])
            )
            return {"done": True, "retailer_notified": True, **_order_summary(session, o)}
        if name == "get_stock":
            q = select(Product).where(Product.maker_id == maker.id)
            if args.get("product_code"):
                q = q.where(Product.code == args["product_code"])
            out = {}
            for p in session.exec(q.order_by(Product.id)):
                rows = {s.size: s.ready for s in session.exec(select(Stock).where(Stock.product_id == p.id))}
                out[p.code] = {
                    "name": p.name,
                    "sizes": {sz: rows.get(sz, 0) for sz in p.size_list()},
                    "pairs_per_day": p.pairs_per_day,
                    "committed_to_production": feasibility.committed_pairs(session, p.id),
                }
            return out or {"error": "No such design"}
        if name == "adjust_stock":
            row = inventory.adjust_stock(
                session, maker, args["product_code"], int(args["size"]), int(args["change"]), actor="Maker"
            )
            return {"done": True, "product_code": args["product_code"], "size": row.size, "ready_now": row.ready}
        if name == "set_stock":
            row = inventory.set_stock(
                session, maker, args["product_code"], int(args["size"]), int(args["ready"]), actor="Maker"
            )
            return {"done": True, "product_code": args["product_code"], "size": row.size, "ready_now": row.ready}
        if name == "set_capacity":
            p = inventory.set_capacity(session, maker, args["product_code"], int(args["pairs_per_day"]), actor="Maker")
            return {"done": True, "design": p.name, "pairs_per_day": p.pairs_per_day}
        if name == "set_price":
            p = inventory.set_price(session, maker, args["product_code"], int(args["price_per_pair"]), actor="Maker")
            return {"done": True, "design": p.name, "price_per_pair": p.price_per_pair}
        if name == "set_message_language":
            m = inventory.set_maker_settings(session, maker, actor="Maker", language=args["language"])
            return {"done": True, "message_language": m.language}
        if name == "set_buffer_days":
            m = inventory.set_maker_settings(session, maker, actor="Maker", buffer_days=int(args["days"]))
            return {"done": True, "buffer_days": m.buffer_days}
        return {"error": f"Unknown tool {name}"}
    except (orders.OrderError, ValueError, KeyError) as e:
        session.rollback()
        if name in WRITE_TOOLS:
            audit.log(
                session,
                "Ops agent",
                "agent.failed",
                f"{name}: {e}",
                maker.id,
                args.get("order_code", "").upper() or None,
            )
            session.commit()
        return {"error": str(e)}


def handle_maker_message(session: Session, maker: Maker, text: str) -> str:
    if not config.ANTHROPIC_API_KEY:
        return i18n.t("maker_help_offline", maker.language)
    designs = "\n".join(
        f"- {p.code}: {p.name}, sizes {p.sizes}"
        for p in session.exec(select(Product).where(Product.maker_id == maker.id).order_by(Product.id))
    )
    system = SYSTEM.format(
        maker=maker.name,
        place=maker.place,
        today=config.today().isoformat(),
        designs=designs,
        language=maker.language or "Marathi",
    )
    maker_id = maker.id
    return run_agent_loop(
        session,
        maker.phone,
        text,
        system,
        TOOLS,
        execute=lambda name, args: run_tool(session, session.get(Maker, maker_id), name, args, text),
        give_up=i18n.t("maker_agent_gave_up", maker.language),
        memory="ops",
    )
