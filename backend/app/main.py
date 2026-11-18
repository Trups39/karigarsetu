"""KarigarSetu API. Run: uvicorn app.main:app --reload   (docs at /docs)"""
import hmac
import json
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlmodel import Session, func, select

from . import accounts, auth, contact, i18n, meta_webhook, whatsapp
from .auth import clean_phone, current_maker, internal_only
from . import config
from .db import engine, get_session, init_db
from .models import AuditLog, Maker, Message, Order, OrderStatus, Product, Retailer, Stock
from .seed import seed
from .services import audit, feasibility, inventory, notify, orders


def _show_app_logs() -> None:
    """Print KarigarSetu's own log lines (agent token use, webhook problems) in the uvicorn terminal."""
    import logging
    lg = logging.getLogger("karigarsetu")
    if not lg.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
        lg.propagate = False


_show_app_logs()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with Session(engine) as s:
        seed(s)
        accounts.relink_accounts(s)   # supplier logins point at the maker with their WhatsApp number
    import logging
    lg = logging.getLogger("karigarsetu")
    if not config.ADMIN_PASSWORD:
        lg.warning("ADMIN_PASSWORD is not set: /admin is off and /docs is open. Set it before going online.")
    from pathlib import Path as _P
    env_file = _P(__file__).resolve().parents[1] / ".env"
    lg.info("Settings file: %s (%s)", env_file, "found" if env_file.exists() else "NOT FOUND")
    if config.SMTP_USERNAME and config.SMTP_PASSWORD:
        lg.info("Email: on, via %s:%s as %s, contact form goes to %s",
                config.SMTP_HOST, config.SMTP_PORT, config.SMTP_USERNAME, config.CONTACT_TO)
    else:
        lg.warning("Email: OFF (SMTP_USERNAME / SMTP_PASSWORD missing in %s). Contact form messages are "
                   "saved but not emailed.", env_file)
    yield


app = FastAPI(title="KarigarSetu API", version="0.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.middleware("http")(accounts.protect_docs)   # /docs, /redoc, /openapi.json: admin only (when ADMIN_PASSWORD is set)
app.include_router(accounts.router)              # /auth/signup, /auth/login, /auth/logout, /admin, /api/admin/*
app.include_router(contact.router)               # /api/contact (website contact form -> Titan email)


@app.exception_handler(orders.OrderError)
async def order_error(_, exc: orders.OrderError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# ---------- request bodies ----------

class Line(BaseModel):
    size: int
    qty: int = Field(gt=0)


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
    price_per_pair: float | int | str | None = None      # checked in add_product (friendly messages)
    pairs_per_day: float | int | str | None = 5
    sizes: str = "6,7,8,9,10"


class ProductPatch(BaseModel):
    price_per_pair: Optional[int] = Field(default=None, gt=0)
    pairs_per_day: Optional[int] = Field(default=None, gt=0)


class MakerPatch(BaseModel):
    buffer_days: Optional[int] = Field(default=None, ge=0)
    min_order: Optional[int] = Field(default=None, ge=1)
    language: Optional[str] = None   # Marathi, Hindi or English


class FeasibilityIn(BaseModel):
    maker_id: int
    product_code: str
    lines: list[Line]


class OrderIn(FeasibilityIn):
    retailer_name: str
    retailer_phone: str
    city: str = ""
    language: str = ""
    source_text: str = ""


class RetailerReplyIn(BaseModel):
    accept: bool


class SimulateIn(BaseModel):
    phone: str
    body: str


# ---------- helpers ----------

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


# ---------- public ----------

@app.get("/health")
def health():
    return {"ok": True, "today": config.today()}


@app.get("/public/makers")
def public_makers(session: Session = Depends(get_session)):
    """Makers shown on the home page: approved (or sample) suppliers that have at least one design.
    "Order on WhatsApp" opens a chat with the KarigarSetu bot, with the maker's name already typed."""
    from urllib.parse import quote

    from .models import AccountStatus, SupplierAccount
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
        out.append({"id": m.id, "name": m.name, "place": m.place, "min_order": m.min_order,
                    "whatsapp": f"https://wa.me/{number}?text={quote(text)}",
                    "designs": [{"name": p.name, "price_per_pair": p.price_per_pair} for p in ps],
                    "price_from": min(p.price_per_pair for p in ps),
                    "pairs_per_day": sum(p.pairs_per_day for p in ps)})
    return out


@app.get("/public/info")
def public_info():
    """Contact details shown on the website."""
    return {"email": config.CONTACT_TO, "whatsapp": config.BOT_WHATSAPP_NUMBER}


# ---------- maker login: see accounts.py (sign-up, email + password, admin approval) ----------


# ---------- maker dashboard ----------

@app.get("/api/me")
def me(maker: Maker = Depends(current_maker)):
    return maker


@app.patch("/api/me")
def update_me(body: MakerPatch, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    return inventory.set_maker_settings(session, maker, **body.model_dump(exclude_none=True))


@app.get("/api/overview")
def overview(maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    pids = [p.id for p in session.exec(select(Product).where(Product.maker_id == maker.id).order_by(Product.id))]
    ready = session.exec(select(func.coalesce(func.sum(Stock.ready), 0)).where(Stock.product_id.in_(pids))).one()
    mine = select(Order).where(Order.maker_id == maker.id)
    count = lambda *st: len(session.exec(mine.where(Order.status.in_(st))).all())  # noqa: E731
    in_prod = sum(o.to_make for o in session.exec(mine.where(Order.status.in_(
        [OrderStatus.approved, OrderStatus.in_production]))))
    return {"pairs_ready": int(ready), "pairs_in_production": in_prod,
            "awaiting_approval": count(OrderStatus.awaiting_maker),
            "upcoming_deliveries": count(OrderStatus.approved, OrderStatus.in_production, OrderStatus.ready),
            "recent_activity": session.exec(select(AuditLog).where(AuditLog.maker_id == maker.id)
                                            .order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(8)).all()}


@app.get("/api/orders")
def list_orders(status: Optional[OrderStatus] = None, maker: Maker = Depends(current_maker),
                session: Session = Depends(get_session)):
    q = select(Order).where(Order.maker_id == maker.id)
    if status:
        q = q.where(Order.status == status)
    return [order_view(session, o) for o in session.exec(q.order_by(Order.created_at.desc(), Order.id.desc()))]


@app.get("/api/orders/{code}")
def get_order(code: str, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    return order_view(session, orders.get_by_code(session, code, maker.id), detail=True)


@app.post("/api/orders/{code}/approve")
def approve(code: str, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    return order_view(session, orders.approve(session, orders.get_by_code(session, code, maker.id)))


@app.post("/api/orders/{code}/reject")
def reject(code: str, body: RejectIn, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    return order_view(session, orders.reject(session, orders.get_by_code(session, code, maker.id), body.reason))


@app.post("/api/orders/{code}/counter")
def counter(code: str, body: CounterIn, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    o = orders.get_by_code(session, code, maker.id)
    return order_view(session, orders.counter(session, o, body.due_date, body.price_per_pair, body.note))


@app.post("/api/orders/{code}/advance")
def advance(code: str, body: AdvanceIn, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    return order_view(session, orders.advance(session, orders.get_by_code(session, code, maker.id), body.to))


@app.get("/api/products")
def products(maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    out = []
    for p in session.exec(select(Product).where(Product.maker_id == maker.id).order_by(Product.id)):
        out.append({**p.model_dump(), "committed": feasibility.committed_pairs(session, p.id)})
    return out


@app.post("/api/products", status_code=201)
def add_product(body: ProductIn, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    """A maker adds a design they sell. Stock starts at 0 for every size."""
    import re

    from . import validation as V
    name = V.design_name(body.name)
    price = V.whole_number(body.price_per_pair, "Price per pair", 1, 100000)
    per_day = V.whole_number(body.pairs_per_day, "Pairs per day", 1, 1000)
    sizes = V.sizes(body.sizes)
    mine = session.exec(select(Product).where(Product.maker_id == maker.id)).all()
    if any(p.name.lower() == name.lower() for p in mine):
        raise HTTPException(409, f"You already have a design called {name}.")
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "design"
    code, n = base, 2
    while any(p.code == code for p in mine):
        code, n = f"{base}-{n}", n + 1
    p = Product(maker_id=maker.id, code=code, name=name, price_per_pair=price,
                pairs_per_day=per_day, sizes=",".join(map(str, sizes)))
    session.add(p)
    session.flush()
    for s in sizes:
        session.add(Stock(product_id=p.id, size=s, ready=0))
    audit.log(session, "Maker", "product.added", f"{name}: ₹{p.price_per_pair}/pair, {p.pairs_per_day} pairs/day, "
              f"sizes {p.sizes}", maker.id)
    data = p.model_dump()   # read before the commit expires it
    session.commit()
    return {**data, "committed": 0}


@app.patch("/api/products/{code}")
def update_product(code: str, body: ProductPatch, maker: Maker = Depends(current_maker),
                   session: Session = Depends(get_session)):
    p = inventory.product(session, maker, code)
    if body.price_per_pair is not None:
        p = inventory.set_price(session, maker, code, body.price_per_pair)
    if body.pairs_per_day is not None:
        p = inventory.set_capacity(session, maker, code, body.pairs_per_day)
    return p


@app.get("/api/stock")
def stock(maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    out = []
    for p in session.exec(select(Product).where(Product.maker_id == maker.id).order_by(Product.id)):
        rows = {s.size: s.ready for s in session.exec(select(Stock).where(Stock.product_id == p.id))}
        out.append({"product_code": p.code, "product_name": p.name,
                    "sizes": {sz: rows.get(sz, 0) for sz in p.size_list()}, "total": sum(rows.values())})
    return out


@app.put("/api/stock")
def set_stock(body: StockIn, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    row = inventory.set_stock(session, maker, body.product_code, body.size, body.ready)
    return {"product_code": body.product_code, "size": body.size, "ready": row.ready}


@app.get("/api/retailers")
def retailers(maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    """Shops that have ordered from this maker, with their order count and total pairs."""
    out = []
    for r in session.exec(select(Retailer).order_by(Retailer.name)):
        mine = session.exec(select(Order).where(Order.maker_id == maker.id, Order.retailer_id == r.id)).all()
        if mine:
            out.append({**r.model_dump(), "orders": len(mine),
                        "pairs": sum(sum(orders.lines_of(session, o).values()) for o in mine)})
    return out


@app.get("/api/audit")
def audit_log(limit: int = 100, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    return session.exec(select(AuditLog).where(AuditLog.maker_id == maker.id)
                        .order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(min(limit, 500))).all()


@app.get("/api/messages")
def messages(limit: int = 50, maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    """WhatsApp messages linked to this maker's orders (useful when Twilio isn't connected)."""
    codes = [o.code for o in session.exec(select(Order).where(Order.maker_id == maker.id))]
    return session.exec(select(Message).where(Message.order_code.in_(codes))
                        .order_by(Message.ts.desc(), Message.id.desc()).limit(min(limit, 200))).all()


# ---------- internal: used by the AI agent, tests and demo tools ----------

@app.post("/internal/feasibility", dependencies=[Depends(internal_only)])
def internal_feasibility(body: FeasibilityIn, session: Session = Depends(get_session)):
    p = session.exec(select(Product).where(Product.maker_id == body.maker_id, Product.code == body.product_code)).first()
    if not p:
        raise HTTPException(404, "Unknown product")
    return feasibility.check(session, p, {ln.size: ln.qty for ln in body.lines}).as_dict()


@app.post("/internal/orders", dependencies=[Depends(internal_only)])
def internal_create_order(body: OrderIn, session: Session = Depends(get_session)):
    lines: dict[int, int] = {}
    for ln in body.lines:
        lines[ln.size] = lines.get(ln.size, 0) + ln.qty
    o, f = orders.create(session, maker_id=body.maker_id, product_code=body.product_code, lines=lines,
                         retailer_name=body.retailer_name, retailer_phone=clean_phone(body.retailer_phone),
                         city=body.city, language=body.language, source_text=body.source_text)
    return {"order": order_view(session, o), "feasibility": f.as_dict()}


@app.post("/internal/orders/{code}/retailer-reply", dependencies=[Depends(internal_only)])
def internal_retailer_reply(code: str, body: RetailerReplyIn, session: Session = Depends(get_session)):
    return order_view(session, orders.retailer_reply(session, orders.get_by_code(session, code), body.accept))


@app.post("/internal/simulate-message", dependencies=[Depends(internal_only)])
def simulate_message(body: SimulateIn, session: Session = Depends(get_session)):
    """Pretend a WhatsApp message arrived. Handy for demos without Twilio."""
    return {"reply": whatsapp.handle_incoming(session, body.phone, body.body)}


# ---------- demo helpers for the dashboard (DEMO_MODE only) ----------

DEMO_RETAILERS = [("Kolhapur Footwear Mart", "Kolhapur", "Marathi", "919811110001"),
                  ("Mumbai Craft Co.", "Mumbai", "English", "919811110002"),
                  ("Indore Juti Ghar", "Indore", "Hindi", "919811110003"),
                  ("Satara Chappal Bazaar", "Satara", "Marathi", "919811110004")]


def demo_only():
    if not config.DEMO_MODE:
        raise HTTPException(404, "Not found")


@app.post("/api/demo/simulate-order", dependencies=[Depends(demo_only)])
def demo_simulate_order(maker: Maker = Depends(current_maker), session: Session = Depends(get_session)):
    """Creates a sample order as if the Sales Agent had drafted it from a WhatsApp message."""
    n = session.exec(select(func.count()).select_from(Order).where(Order.maker_id == maker.id)).one()
    products_ = session.exec(select(Product).where(Product.maker_id == maker.id).order_by(Product.id)).all()
    if not products_:
        raise HTTPException(409, "Add your designs first (Products), then simulate an order.")
    pune = session.exec(select(Retailer).where(Retailer.name == "Pune Footwear House")).first()
    pune_phone = pune.phone if pune else "919811112222"
    pune_done = session.exec(select(Order).where(Order.maker_id == maker.id,
                                                 Order.retailer_phone == pune_phone)).first()
    if not pune_done:   # the first one is the demo story: a Pune shop orders 50 pairs
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
    o, _ = orders.create(session, maker_id=maker.id, product_code=p.code, lines=lines, retailer_name=name,
                         retailer_phone=phone, city=city, language=lang, source_text="(simulated WhatsApp order)")
    return order_view(session, o)


@app.post("/api/demo/orders/{code}/retailer-reply", dependencies=[Depends(demo_only)])
def demo_retailer_reply(code: str, body: RetailerReplyIn, maker: Maker = Depends(current_maker),
                        session: Session = Depends(get_session)):
    return order_view(session, orders.retailer_reply(session, orders.get_by_code(session, code, maker.id), body.accept))


# ---------- WhatsApp webhook (Twilio format) ----------

def _process_whatsapp(phone: str, body: str) -> None:
    with Session(engine) as session:
        try:
            whatsapp.handle_incoming(session, phone, body)
        except Exception:   # never let one bad message stop the server; it's in the log
            import logging
            logging.getLogger("karigarsetu.webhook").exception("Failed to handle message from %s", phone)


@app.post("/webhooks/whatsapp")
def whatsapp_webhook(background: BackgroundTasks, From: str = Form(...), Body: str = Form("")):
    """Twilio calls this for every incoming WhatsApp message.

    We answer Twilio straight away and do the work (Claude, database, replies) in the background,
    because Claude can take several seconds and Twilio expects a quick response.
    """
    # TODO before production: verify the X-Twilio-Signature header.
    background.add_task(_process_whatsapp, From, Body)
    return Response(content="<Response/>", media_type="application/xml")   # replies are sent via the API


# ---------- WhatsApp webhook (Meta WhatsApp Cloud API) ----------

def _process_meta(items: list) -> None:
    with Session(engine) as session:
        for m in items:
            try:
                if m.text.strip():
                    whatsapp.handle_incoming(session, m.phone, m.text)
                else:   # voice note, photo, sticker...: ask for text
                    phone = auth.clean_phone(m.phone)
                    notify.record_incoming(session, phone, f"[{m.kind} message]")
                    notify.send(session, phone, i18n.t("not_text", whatsapp.language_for(session, phone)))
                    session.commit()
            except Exception:   # one bad message must not stop the others; details are in the log
                import logging
                session.rollback()
                logging.getLogger("karigarsetu.webhook").exception("Failed to handle Meta message from %s", m.phone)


@app.get("/webhooks/meta", include_in_schema=False)
def meta_verify(request: Request):
    """Meta calls this once when you click "Verify and save" on the webhook form."""
    q = request.query_params
    if (q.get("hub.mode") == "subscribe" and config.META_VERIFY_TOKEN
            and hmac.compare_digest(q.get("hub.verify_token", ""), config.META_VERIFY_TOKEN)):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "Verify token doesn't match META_VERIFY_TOKEN in backend/.env")


@app.post("/webhooks/meta", include_in_schema=False)
async def meta_webhook_in(request: Request, background: BackgroundTasks):
    """Every WhatsApp message to the bot number arrives here. We answer Meta at once and
    do the work (Claude, database, replies) in the background, as Meta expects a quick 200."""
    raw = await request.body()
    if not meta_webhook.signature_ok(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(403, "Bad signature. Check META_APP_SECRET in backend/.env")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "Not JSON")
    items = [m for m in meta_webhook.extract_messages(payload) if meta_webhook.seen.first_time(m.message_id)]
    if items:
        background.add_task(_process_meta, items)
    return {"ok": True}


# ---------- website (served from the same server, so the dashboard can call the API) ----------

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "index.html"   # karigarsetu/frontend/index.html


@app.get("/", include_in_schema=False)
def website():
    return FileResponse(FRONTEND)


app.mount("/assets", StaticFiles(directory=FRONTEND.parent / "assets"), name="assets")
