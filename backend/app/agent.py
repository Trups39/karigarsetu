"""Sales Agent (retailers): Claude reads the retailer's WhatsApp message and calls backend tools.

Claude only interprets language and fills in tool arguments. Prices, stock, dates and order creation
all come from the deterministic services, and nothing is promised until the maker approves.
"""
import json
import logging

from sqlmodel import Session, select

from . import config
from .models import Conversation, Maker, Order, Product, Retailer, utcnow
from .services import feasibility, orders

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
    {"name": "list_products", "description": "Designs a maker sells, with price per pair and sizes.",
     "input_schema": {"type": "object", "properties": {"maker_id": {"type": "integer"}}, "required": ["maker_id"]}},
    {"name": "check_feasibility",
     "description": "How many pairs are ready now, how many must be made, and the earliest delivery date.",
     "input_schema": {"type": "object", "properties": {
         "maker_id": {"type": "integer"}, "product_code": {"type": "string"},
         "lines": {"type": "array", "items": {"type": "object", "properties": {
             "size": {"type": "integer"}, "qty": {"type": "integer"}}, "required": ["size", "qty"]}}},
         "required": ["maker_id", "product_code", "lines"]}},
    {"name": "create_order",
     "description": "Create the order and send it to the maker for approval. Only call once all details are known.",
     "input_schema": {"type": "object", "properties": {
         "maker_id": {"type": "integer"}, "product_code": {"type": "string"},
         "lines": {"type": "array", "items": {"type": "object", "properties": {
             "size": {"type": "integer"}, "qty": {"type": "integer"}}, "required": ["size", "qty"]}},
         "retailer_name": {"type": "string", "description": "Shop name"},
         "city": {"type": "string"},
         "language": {"type": "string", "enum": ["Marathi", "Hindi", "English"]},
         "source_text": {"type": "string", "description": "The retailer's original order message"}},
         "required": ["maker_id", "product_code", "lines", "retailer_name", "city", "language"]}},
    {"name": "get_order_status", "description": "Status of one of this retailer's orders.",
     "input_schema": {"type": "object", "properties": {"order_code": {"type": "string"}}, "required": ["order_code"]}},
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
            return {"products": [{"code": p.code, "name": p.name, "price_per_pair": p.price_per_pair,
                                  "sizes": p.size_list()} for p in ps]}
        if name == "check_feasibility":
            p = session.exec(select(Product).where(Product.maker_id == args["maker_id"],
                                                   Product.code == args["product_code"])).first()
            if not p:
                return {"error": "Unknown product"}
            return feasibility.check(session, p, _lines(args["lines"])).as_dict()
        if name == "create_order":
            order, f = orders.create(
                session, maker_id=args["maker_id"], product_code=args["product_code"], lines=_lines(args["lines"]),
                retailer_name=args["retailer_name"], retailer_phone=retailer_phone, city=args.get("city", ""),
                language=args.get("language", ""), source_text=args.get("source_text", ""))
            return {"order_code": order.code, "status": "sent to maker for approval", "feasibility": f.as_dict()}
        if name == "get_order_status":
            o = session.exec(select(Order).where(Order.code == args["order_code"].upper(),
                                                 Order.retailer_phone == retailer_phone)).first()
            if not o:
                return {"error": "No such order for this phone number"}
            return {"order_code": o.code, "status": orders.STATUS_TEXT[o.status],
                    "due_date": o.due_date.isoformat() if o.due_date else None}
        return {"error": f"Unknown tool {name}"}
    except orders.OrderError as e:
        session.rollback()
        return {"error": str(e)}


def _trim(history: list, keep: int = 30) -> list:
    """Keep recent turns, starting on a plain user text message so tool_use/tool_result pairs stay intact."""
    if len(history) <= keep:
        return history
    for i in range(len(history) - keep, len(history)):
        m = history[i]
        if m["role"] == "user" and isinstance(m["content"], str):
            return history[i:]
    return history[-1:]


def whatsapp_format(text: str) -> str:
    """Turn website-style markdown into WhatsApp style: **bold** -> *bold*, drop # headings."""
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"__(.+?)__", r"_\1_", text)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    return text


def _clean_block(b) -> dict:
    """Keep only the fields the API accepts back as input (newer SDKs add extra output-only fields).
    Thinking blocks are passed back unchanged within a turn, as the API requires."""
    if b.type == "text":
        return {"type": "text", "text": b.text}
    if b.type == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    if b.type == "thinking":
        return {"type": "thinking", "thinking": b.thinking, "signature": b.signature}
    if b.type == "redacted_thinking":
        return {"type": "redacted_thinking", "data": b.data}
    return b.model_dump(exclude_none=True)


def _for_memory(history: list) -> list:
    """What we keep between messages: no thinking blocks. They are tied to the exact instructions and
    tools of the reply that made them, and the API allows dropping them from earlier turns."""
    out = []
    for m in history:
        content = m["content"]
        if isinstance(content, list):
            content = [c for c in content if c.get("type") not in ("thinking", "redacted_thinking")]
            if not content:
                continue
        out.append({"role": m["role"], "content": content})
    return out


CACHE = {"type": "ephemeral"}


def _cached_request(system: str, tools: list, history: list) -> dict:
    """Prompt caching: mark the tools, the system prompt and the conversation so far as cacheable.
    The next call (the next step of the tool loop, or the person's next message within a few minutes)
    re-reads them from Anthropic's cache: cheaper and faster. The saved history is not changed."""
    tools_c = [dict(t) for t in tools]
    if tools_c:
        tools_c[-1]["cache_control"] = CACHE
    messages = [dict(m) for m in history]
    if messages:
        last = messages[-1]
        content = last["content"]
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else [dict(b) for b in content]
        if blocks:
            blocks[-1]["cache_control"] = CACHE
            messages[-1] = {"role": last["role"], "content": blocks}
    return {"system": [{"type": "text", "text": system, "cache_control": CACHE}], "tools": tools_c,
            "messages": messages}


def _log_usage(resp) -> None:
    u = getattr(resp, "usage", None)
    if u is not None:
        log.info("Claude tokens: input %s, cache read %s, cache write %s, output %s",
                 getattr(u, "input_tokens", "?"), getattr(u, "cache_read_input_tokens", 0),
                 getattr(u, "cache_creation_input_tokens", 0), getattr(u, "output_tokens", "?"))


NUDGE = ("(Note from the system, not the customer: you ended without a message. Write your WhatsApp reply "
         "to the person now, in their language.)")


def _converse(client, system: str, tools: list, history: list, execute) -> str | None:
    """One user turn: call Claude, run any tools it asks for, until it answers. None = gave up.
    If Claude stops without any text (it ran out of room, or forgot), it is asked once for the reply."""
    nudged = False
    for _ in range(8):   # tool-use loop
        resp = client.messages.create(model=config.CLAUDE_MODEL, max_tokens=config.CLAUDE_MAX_TOKENS,
                                      **_cached_request(system, tools, history))
        _log_usage(resp)
        if resp.stop_reason == "max_tokens":   # cut off: a half-written tool call can't be sent back
            log.warning("Claude hit max_tokens (%s); asking for the reply again", config.CLAUDE_MAX_TOKENS)
            blocks = [b for b in resp.content if b.type == "text"]
        else:
            blocks = list(resp.content)
        if blocks:
            history.append({"role": "assistant", "content": [_clean_block(b) for b in blocks]})
        if resp.stop_reason != "tool_use":
            text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
            if text and resp.stop_reason != "max_tokens":
                return whatsapp_format(text)
            if nudged:
                return whatsapp_format(text) if text else None
            nudged = True
            history.append({"role": "user", "content": NUDGE})
            continue
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                out = execute(b.name, b.input)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out, default=str)})
        history.append({"role": "user", "content": results})
    return None


def run_agent_loop(session: Session, phone: str, text: str, system: str, tools: list, execute,
                   give_up: str, memory: str = "sales") -> str:
    """Shared Claude tool-use loop for both agents. execute(name, args) -> dict runs one tool.

    Chat memory is kept per agent and phone ("sales:<phone>" / "ops:<phone>") in the Conversation table.
    If anything fails, the person gets a polite message instead of an error, and the details go to the
    server log. If Claude rejects the saved history (status 400), it is cleared and the message retried once.
    """
    import anthropic

    key = f"{memory}:{phone}"   # separate memory per agent, so a number that changes role never mixes chats
    conv = session.get(Conversation, key) or Conversation(phone=key)
    saved = _for_memory(json.loads(conv.history))
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    history, reply = None, None
    for attempt, start in enumerate((saved, [])):
        history = start + [{"role": "user", "content": text}]
        try:
            reply = _converse(client, system, tools, history, execute)
            break
        except Exception as e:   # noqa: BLE001  (never crash the webhook)
            status = getattr(e, "status_code", None)
            if attempt == 0 and status == 400 and saved:
                log.warning("Claude rejected saved history for %s (%s); retrying with a fresh chat", phone, e)
                continue
            log.exception("Agent failed for %s", phone)
            session.rollback()
            return give_up

    if reply is None:
        reply = give_up
    conv = session.get(Conversation, key) or Conversation(phone=key)   # re-fetch: a tool may have rolled back
    conv.history = json.dumps(_trim(_for_memory(history)), default=str)
    conv.updated_at = utcnow()
    session.add(conv)
    session.commit()
    return reply or "👍"


def handle_retailer_message(session: Session, phone: str, text: str) -> str:
    """Sales Agent: retailers ordering on WhatsApp."""
    from . import i18n
    known = session.exec(select(Retailer).where(Retailer.phone == phone)).first()
    lang = i18n.norm(known.language) if known and known.language else i18n.detect(text)
    if not config.ANTHROPIC_API_KEY:
        return i18n.t("retailer_offline", lang)
    makers = session.exec(select(Maker).order_by(Maker.id)).all()
    retailer = (f"returning shop {known.name}, {known.city}, prefers {known.language or 'any language'}. "
                "Don't ask for their shop name or city again." if known else "new; ask for their shop name and city.")
    def designs(m):
        ps = session.exec(select(Product).where(Product.maker_id == m.id).order_by(Product.id)).all()
        return ", ".join(f"{p.name} ₹{p.price_per_pair}" for p in ps) or "no designs yet (can't take orders)"
    system = SYSTEM.format(makers="\n".join(f"- id {m.id}: {m.name}, {m.place}, minimum {m.min_order} pairs. "
                                             f"Designs: {designs(m)}" for m in makers),
                           retailer=retailer)
    return run_agent_loop(session, phone, text, system, TOOLS,
                          execute=lambda name, args: run_tool(session, name, args, phone),
                          give_up=i18n.t("retailer_agent_gave_up", lang))
