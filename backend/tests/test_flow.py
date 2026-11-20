"""End-to-end tests. Run: pytest -q"""

# Test settings (SQLite by default, PostgreSQL with TEST_DATABASE_URL) are in tests/conftest.py.

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app.core import config  # noqa: E402
from app.core.db import engine  # noqa: E402
from app.main import app  # noqa: E402

INTERNAL = {"X-Internal-Key": "test-key"}
SHINDE, PATIL = "919800000001", "919800000002"
RETAILER = "919811112222"


@pytest.fixture()
def client():
    SQLModel.metadata.drop_all(engine)
    with TestClient(app) as c:  # lifespan creates tables and seeds
        yield c


def login(c, phone):
    """Log in as the maker with this WhatsApp number (gives them an approved test account first)."""
    from sqlmodel import Session, select

    from app.core.models import AccountStatus, Maker, SupplierAccount
    from app.services.accounts import hash_password

    with Session(engine) as s:
        m = s.exec(select(Maker).where(Maker.phone == phone)).first()
        a = s.exec(select(SupplierAccount).where(SupplierAccount.phone == phone)).first()
        if not a:
            a = SupplierAccount(
                name="Test",
                business_name=m.name,
                town=m.place,
                phone=phone,
                email=f"{phone}@test.in",
                password_hash="",
                status=AccountStatus.approved,
                maker_id=m.id,
            )
        a.password_hash = hash_password("testpass123")  # sample suppliers have no password: give one for the test
        s.add(a)
        s.commit()
        email = a.email
    r = c.post("/auth/login", json={"email": email, "password": "testpass123"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def pune_order(c, lines=None):
    body = {
        "maker_id": 1,
        "product_code": "classic",
        "retailer_name": "Pune Footwear House",
        "retailer_phone": RETAILER,
        "city": "Pune",
        "language": "Marathi",
        "lines": lines or [{"size": 7, "qty": 15}, {"size": 8, "qty": 20}, {"size": 9, "qty": 15}],
    }
    r = c.post("/internal/orders", json=body, headers=INTERNAL)
    assert r.status_code == 200, r.text
    return r.json()


def test_pune_order_full_flow(client):
    h = login(client, SHINDE)
    res = pune_order(client)
    f, code = res["feasibility"], res["order"]["code"]
    assert (f["ready"], f["to_make"]) == (20, 30)  # 6 + 8 + 6 ready
    assert f["earliest_date"] == "2026-11-24"  # ceil(30/6)=5 days + 3 buffer
    assert res["order"]["status"] == "awaiting_maker"

    # Maker approves by replying "1" on WhatsApp
    r = client.post("/internal/simulate-message", json={"phone": "+91 98000 00001", "body": "1"}, headers=INTERNAL)
    assert "मंजूर" in r.json()["reply"]  # maker gets Marathi

    o = client.get(f"/api/orders/{code}", headers=h).json()
    assert o["status"] == "approved" and o["due_date"] == "2026-11-24"
    assert (o["reserved_ready"], o["to_make"]) == (20, 30)
    assert any(
        "कन्फर्म" in m["body"] and "24 नोव्हेंबर 2026" in m["body"] and m["phone"] == RETAILER for m in o["messages"]
    )  # Marathi shop
    actions = [a["action"] for a in o["audit"]]
    assert actions[:3] == ["order.drafted", "order.feasibility", "maker.notified"]
    assert "order.approved" in actions and "stock.reserved" in actions

    stock = {s["product_code"]: s["sizes"] for s in client.get("/api/stock", headers=h).json()}
    assert stock["classic"] == {"6": 4, "7": 0, "8": 0, "9": 0, "10": 3}
    assert client.get("/api/overview", headers=h).json()["pairs_in_production"] == 30

    for step in ["in_production", "ready", "delivered"]:
        r = client.post(f"/api/orders/{code}/advance", json={"to": step}, headers=h)
        assert r.json()["status"] == step
    assert client.post(f"/api/orders/{code}/advance", json={"to": "ready"}, headers=h).status_code == 409


def test_committed_production_pushes_later_orders(client):
    h = login(client, SHINDE)
    first = pune_order(client)["order"]["code"]
    client.post(f"/api/orders/{first}/approve", headers=h)
    # size 7 stock is now 0, so all 20 must be made after the 30 already booked
    f = pune_order(client, [{"size": 7, "qty": 20}])["feasibility"]
    assert (f["ready"], f["to_make"], f["already_committed"]) == (0, 20, 30)
    assert f["earliest_date"] == "2026-11-28"  # ceil(50/6)=9 + 3


def test_counter_offer_accepted_by_retailer(client):
    h = login(client, SHINDE)
    code = pune_order(client)["order"]["code"]
    r = client.post(f"/api/orders/{code}/counter", json={"due_date": "2026-12-01", "price_per_pair": 600}, headers=h)
    assert r.json()["status"] == "counter_offered"
    client.post("/internal/simulate-message", json={"phone": RETAILER, "body": "हो"}, headers=INTERNAL)
    o = client.get(f"/api/orders/{code}", headers=h).json()
    assert o["status"] == "approved" and o["price_per_pair"] == 600 and o["due_date"] == "2026-12-01"
    assert o["total_price"] == 30000


def test_counter_offer_declined(client):
    h = login(client, SHINDE)
    code = pune_order(client)["order"]["code"]
    client.post(f"/api/orders/{code}/counter", json={"price_per_pair": 650}, headers=h)
    client.post("/internal/simulate-message", json={"phone": RETAILER, "body": "no"}, headers=INTERNAL)
    assert client.get(f"/api/orders/{code}", headers=h).json()["status"] == "rejected"


def test_maker_whatsapp_counter_with_date_and_price(client):
    h = login(client, SHINDE)
    code = pune_order(client)["order"]["code"]
    r = client.post(
        "/internal/simulate-message", json={"phone": SHINDE, "body": f"3 {code} 2026-12-03 575"}, headers=INTERNAL
    )
    assert "प्रस्ताव" in r.json()["reply"]
    o = client.get(f"/api/orders/{code}", headers=h).json()
    assert (o["status"], o["price_per_pair"], o["due_date"]) == ("counter_offered", 575, "2026-12-03")


def test_rules_and_permissions(client):
    assert client.get("/api/orders").status_code == 401
    assert client.post("/auth/login", json={"email": "nobody@test.in", "password": "wrong-pass"}).status_code == 401
    assert client.post("/internal/orders", json={}, headers={"X-Internal-Key": "wrong"}).status_code == 403

    bad_size = {
        "maker_id": 1,
        "product_code": "classic",
        "retailer_name": "X",
        "retailer_phone": RETAILER,
        "lines": [{"size": 13, "qty": 30}],
    }
    assert client.post("/internal/orders", json=bad_size, headers=INTERNAL).status_code == 409
    too_small = {**bad_size, "lines": [{"size": 8, "qty": 5}]}
    r = client.post("/internal/orders", json=too_small, headers=INTERNAL)
    assert r.status_code == 409 and "Minimum order" in r.json()["detail"]

    code = pune_order(client)["order"]["code"]
    other = login(client, PATIL)
    assert client.get(f"/api/orders/{code}", headers=other).status_code == 409  # not their order
    h = login(client, SHINDE)
    client.post(f"/api/orders/{code}/reject", json={"reason": "Leather shortage"}, headers=h)
    assert client.post(f"/api/orders/{code}/approve", headers=h).status_code == 409  # already rejected


def test_stock_and_capacity_updates_change_dates(client):
    h = login(client, SHINDE)
    assert (
        client.put("/api/stock", json={"product_code": "classic", "size": 8, "ready": 20}, headers=h).status_code == 200
    )
    client.patch("/api/products/classic", json={"pairs_per_day": 10}, headers=h)
    client.patch("/api/me", json={"buffer_days": 1}, headers=h)
    f = client.post(
        "/internal/feasibility",
        headers=INTERNAL,
        json={"maker_id": 1, "product_code": "classic", "lines": [{"size": 8, "qty": 50}]},
    ).json()
    assert (f["ready"], f["to_make"], f["earliest_date"]) == (20, 30, "2026-11-20")  # 3 days + 1 buffer


def test_agent_offline_fallback(client):
    r = client.post("/internal/simulate-message", json={"phone": RETAILER, "body": "50 jodya pahije"}, headers=INTERNAL)
    assert "सहाय्यक सध्या बंद" in r.json()["reply"]  # known Marathi shop


def test_agent_quotes_first_and_creates_the_order_only_after_the_shops_yes(client, monkeypatch):
    """Fake Claude. Message 1: feasibility, then it tries to create the order straight away (the code refuses)
    and sends the quote. Message 2 ("हो"): the order is created with the shop's price request for the maker."""
    from types import SimpleNamespace as NS

    import anthropic

    lines = [{"size": 7, "qty": 15}, {"size": 8, "qty": 20}, {"size": 9, "qty": 15}]
    order_args = {
        "maker_id": 1,
        "product_code": "classic",
        "lines": lines,
        "retailer_name": "Pune Footwear House",
        "city": "Pune",
        "language": "Marathi",
        "source_text": "मला क्लासिक 50 जोड्या हव्यात",
    }

    def tool(name, args, i):
        b = NS(type="tool_use", id=f"t{i}", name=name, input=args)
        b.model_dump = lambda **_: {"type": "tool_use", "id": b.id, "name": name, "input": args}
        return b

    def text(t):
        b = NS(type="text", text=t)
        b.model_dump = lambda **_: {"type": "text", "text": t}
        return b

    script = [
        # message 1
        NS(
            stop_reason="tool_use",
            content=[tool("check_feasibility", {"maker_id": 1, "product_code": "classic", "lines": lines}, 1)],
        ),
        NS(stop_reason="tool_use", content=[tool("create_order", order_args, 2)]),  # too early: refused
        NS(stop_reason="end_turn", content=[text("50 जोड्या: 20 तयार, 30 बनवायच्या. ₹27,500. मेकरकडे पाठवू? हो / नाही")]),
        # message 2: the shop says yes and asks for a lower price
        NS(
            stop_reason="tool_use",
            content=[tool("create_order", {**order_args, "retailer_request": "₹520 per pair if possible"}, 3)],
        ),
        NS(stop_reason="end_turn", content=[text("ऑर्डर KS-1041 मेकरकडे मंजुरीसाठी पाठवली आहे.")]),
    ]
    seen_tool_results = []

    class FakeClient:
        def __init__(self, **_):
            self.messages = self

        def create(self, **kw):
            last = kw["messages"][-1]
            if isinstance(last["content"], list) and last["content"][0].get("type") == "tool_result":
                seen_tool_results.append(last["content"][0]["content"])
            return script.pop(0)

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "fake")
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    h = login(client, SHINDE)

    r = client.post(
        "/internal/simulate-message", json={"phone": RETAILER, "body": "मला क्लासिक 50 जोड्या हव्यात"}, headers=INTERNAL
    )
    assert "हो / नाही" in r.json()["reply"]
    assert '"ready": 20' in seen_tool_results[0] and "Not created" in seen_tool_results[1]
    assert client.get("/api/orders", headers=h).json() == []  # nothing sent to the maker yet

    r = client.post(
        "/internal/simulate-message", json={"phone": RETAILER, "body": "हो, 520 ला जमेल का?"}, headers=INTERNAL
    )
    assert "KS-1041" in r.json()["reply"] and "KS-1041" in seen_tool_results[2]
    o = client.get("/api/orders", headers=h).json()[0]
    assert (o["code"], o["retailer_phone"], o["price_per_pair"]) == ("KS-1041", RETAILER, 550)  # list price kept
    to_maker = client.get("/api/messages", headers=h).json()
    assert any("₹520 per pair if possible" in m["body"] and "KS-1041" in m["body"] for m in to_maker)


def test_create_order_needs_a_matching_quote_from_an_earlier_message():
    from app.agents import sales

    args = {"maker_id": 1, "product_code": "classic", "lines": [{"size": 8, "qty": 30}]}
    sales._quotes.clear()
    assert sales.run_tool(
        None, "create_order", {**args, "retailer_name": "X", "city": "Y", "language": "English"}, "91", 2
    ) == {"error": sales.NEEDS_YES}
    sales._quotes["91"] = (sales._quote_key(args), 1)
    other = {**args, "lines": [{"size": 8, "qty": 40}]}  # the shop changed the quantity: needs a new quote
    assert sales.run_tool(
        None, "create_order", {**other, "retailer_name": "X", "city": "Y", "language": "English"}, "91", 2
    ) == {"error": sales.NEEDS_YES}
    sales._quotes["91"] = (sales._quote_key(args), 2)  # quote sent in this same message
    assert sales.run_tool(
        None, "create_order", {**args, "retailer_name": "X", "city": "Y", "language": "English"}, "91", 2
    ) == {"error": sales.NEEDS_YES}
    sales._quotes.clear()


def test_website_and_demo_endpoints(client):
    assert "KarigarSetu" in client.get("/").text
    h = login(client, SHINDE)
    first = client.post("/api/demo/simulate-order", headers=h).json()
    assert (first["code"], first["retailer_name"], first["total_pairs"]) == ("KS-1041", "Pune Footwear House", 50)
    client.post(f"/api/orders/{first['code']}/counter", json={"price_per_pair": 590}, headers=h)
    r = client.post(f"/api/demo/orders/{first['code']}/retailer-reply", json={"accept": True}, headers=h)
    assert r.json()["status"] == "approved"


def test_demo_orders_from_sql_files(client, monkeypatch):
    """Reload with db/demo_orders.sql: history shows, and the Pune demo still comes out the same."""
    from sqlmodel import Session

    from app import seed as seed_mod

    monkeypatch.setattr(config, "SEED_DEMO_ORDERS", True)
    seed_mod.reset()
    with Session(engine) as s:
        assert seed_mod.seed(s) is True
        assert seed_mod.seed(s) is False  # second run does nothing

    h = login(client, SHINDE)
    codes = {o["code"]: o["status"] for o in client.get("/api/orders", headers=h).json()}
    assert codes == {"KS-1036": "delivered", "KS-1039": "in_production"}
    kapshi = next(p for p in client.get("/api/products", headers=h).json() if p["code"] == "kapshi")
    assert kapshi["committed"] == 24
    assert client.get("/api/overview", headers=h).json()["pairs_in_production"] == 24
    shops = {r["name"]: r["orders"] for r in client.get("/api/retailers", headers=h).json()}
    assert shops == {"Mumbai Craft Co.": 1, "Nashik Heritage Store": 1}
    assert any(a["order_code"] == "KS-1039" for a in client.get("/api/audit", headers=h).json())

    pune = client.post("/api/demo/simulate-order", headers=h).json()
    assert (pune["code"], pune["retailer_name"], pune["total_pairs"]) == ("KS-1041", "Pune Footwear House", 50)
    d = client.get(f"/api/orders/{pune['code']}", headers=h).json()["feasibility"]
    assert (d["ready"], d["to_make"], d["earliest_date"]) == (20, 30, "2026-11-24")
    nxt = client.post("/api/demo/simulate-order", headers=h).json()
    assert nxt["code"] == "KS-1042" and nxt["retailer_name"] != "Pune Footwear House"


def test_returning_retailer_is_reused(client):
    pune_order(client)
    pune_order(client, [{"size": 6, "qty": 25}])
    h = login(client, SHINDE)
    shops = client.get("/api/retailers", headers=h).json()
    assert len(shops) == 1 and shops[0]["orders"] == 2 and shops[0]["pairs"] == 75


# ---------- Operations Agent (maker side) ----------


def fake_claude(monkeypatch, steps):
    """steps: list of ("tool", name, args) or ("text", reply). Returns the tool results Claude was sent."""
    from types import SimpleNamespace as NS

    import anthropic

    def block_tool(name, args, i):
        b = NS(type="tool_use", id=f"t{i}", name=name, input=args)
        b.model_dump = lambda **_: {"type": "tool_use", "id": b.id, "name": name, "input": args}
        return b

    def block_text(t):
        b = NS(type="text", text=t)
        b.model_dump = lambda **_: {"type": "text", "text": t}
        return b

    script = [
        NS(stop_reason="tool_use", content=[block_tool(s[1], s[2], i)])
        if s[0] == "tool"
        else NS(stop_reason="end_turn", content=[block_text(s[1])])
        for i, s in enumerate(steps)
    ]
    seen = []

    class FakeClient:
        def __init__(self, **_):
            self.messages = self

        def create(self, **kw):
            last = kw["messages"][-1]
            if isinstance(last["content"], list) and last["content"][0].get("type") == "tool_result":
                seen.append(last["content"][0]["content"])
            system = kw["system"] if isinstance(kw["system"], str) else "".join(b["text"] for b in kw["system"])
            seen.append(("system", system)) if not seen else None
            return script.pop(0)

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "fake")
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    return seen


def maker_says(c, text, phone=SHINDE):
    return c.post("/internal/simulate-message", json={"phone": phone, "body": text}, headers=INTERNAL).json()["reply"]


def test_ops_agent_lists_pending_orders_in_marathi(client, monkeypatch):
    code = pune_order(client)["order"]["code"]
    seen = fake_claude(
        monkeypatch,
        [
            ("tool", "list_orders", {"status": "awaiting_maker"}),
            ("text", f"आज 1 ऑर्डर बाकी आहे: {code}, Pune Footwear House, 50 जोड्या."),
        ],
    )
    reply = maker_says(client, "आज किती ऑर्डर बाकी आहेत?")
    assert code in reply
    assert "Kolhapur Chappal Kendra" in seen[0][1] and "Today is 2026-11-16" in seen[0][1]  # system prompt
    assert code in seen[1] and '"pairs": 50' in seen[1]


def test_ops_agent_adds_stock(client, monkeypatch):
    h = login(client, SHINDE)
    fake_claude(
        monkeypatch,
        [
            ("tool", "adjust_stock", {"product_code": "classic", "size": 8, "change": 10}),
            ("text", "Classic size 8: 10 jodi add kele. Ata 18 ready."),
        ],
    )
    assert "18" in maker_says(client, "Size 8 Classic 10 jodi add kar")
    stock = {s["product_code"]: s["sizes"] for s in client.get("/api/stock", headers=h).json()}
    assert stock["classic"]["8"] == 18
    actions = [a["action"] for a in client.get("/api/audit", headers=h).json()]
    assert "agent.action" in actions and "stock.updated" in actions


def test_ops_agent_approves_with_own_date(client, monkeypatch):
    h = login(client, SHINDE)
    code = pune_order(client)["order"]["code"]
    fake_claude(
        monkeypatch,
        [
            ("tool", "approve_order", {"order_code": code, "due_date": "2026-12-05"}),
            ("text", f"{code} approve kela, delivery 5 December. Retailer la kalavla."),
        ],
    )
    maker_says(client, f"{code} approve kar, pan delivery 5 December")
    o = client.get(f"/api/orders/{code}", headers=h).json()
    assert (o["status"], o["due_date"]) == ("approved", "2026-12-05")
    assert any("5 डिसेंबर 2026" in m["body"] and m["phone"] == RETAILER for m in o["messages"])


def test_ops_agent_cannot_break_rules(client, monkeypatch):
    h = login(client, SHINDE)
    shinde_code = pune_order(client)["order"]["code"]
    patil_body = {
        "maker_id": 2,
        "product_code": "pukari",
        "retailer_name": "X",
        "retailer_phone": "919800009999",
        "lines": [{"size": 8, "qty": 30}],
    }
    patil_code = client.post("/internal/orders", json=patil_body, headers=INTERNAL).json()["order"]["code"]

    seen = fake_claude(
        monkeypatch,
        [
            ("tool", "approve_order", {"order_code": patil_code}),  # another maker's order
            ("tool", "adjust_stock", {"product_code": "classic", "size": 8, "change": -500}),  # more than in stock
            ("tool", "approve_order", {"order_code": shinde_code, "due_date": "2026-01-01"}),  # date in the past
            ("tool", "set_price", {"product_code": "classic", "price_per_pair": 0}),  # invalid price
            ("text", "I couldn't do those."),
        ],
    )
    maker_says(client, "do everything")
    errors = [r for r in seen[1:] if isinstance(r, str)]
    assert all('"error"' in r for r in errors) and len(errors) == 4
    assert "not found" in errors[0]

    patil = login(client, PATIL)
    assert client.get(f"/api/orders/{patil_code}", headers=patil).json()["status"] == "awaiting_maker"
    assert client.get(f"/api/orders/{shinde_code}", headers=h).json()["status"] == "awaiting_maker"
    stock = {r["product_code"]: r["sizes"] for r in client.get("/api/stock", headers=h).json()}
    assert stock["classic"]["8"] == 8
    failed = [a for a in client.get("/api/audit", headers=h).json() if a["action"] == "agent.failed"]
    assert len(failed) == 4


def test_maker_quick_reply_still_works_and_agent_offline_help(client):
    code = pune_order(client)["order"]["code"]
    assert "मंजुरीसाठी 1" in maker_says(client, "hello")  # no API key: help text, in Marathi
    assert f"{code} मंजूर" in maker_says(client, "1")  # quick reply needs no AI


def test_no_unsigned_webhook(client):
    """Only the Meta webhook (signature-checked) accepts WhatsApp messages; there is no other way in."""
    assert client.post("/webhooks/whatsapp", data={"From": "whatsapp:+919800000001", "Body": "1"}).status_code in (
        404,
        405,
    )


# ---------- Meta WhatsApp Cloud API ----------


def meta_payload(phone, text=None, msg_id="wamid.1", kind="text"):
    msg = {"from": phone, "id": msg_id, "timestamp": "1763390000", "type": kind}
    if kind == "text":
        msg["text"] = {"body": text}
    elif kind == "audio":
        msg["audio"] = {"id": "media1", "mime_type": "audio/ogg"}
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "15550001111", "phone_number_id": "PNID"},
                            "contacts": [{"profile": {"name": "Test"}, "wa_id": phone}],
                            "messages": [msg],
                        },
                    }
                ],
            }
        ],
    }


def meta_post(c, payload, secret="app-secret", sign=True):
    import hashlib
    import hmac
    import json as _json

    raw = _json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if sign:
        headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return c.post("/webhooks/meta", content=raw, headers=headers)


@pytest.fixture()
def meta(monkeypatch):
    monkeypatch.setattr(config, "META_VERIFY_TOKEN", "karigar-verify")
    monkeypatch.setattr(config, "META_APP_SECRET", "app-secret")


def test_meta_webhook_verification(client, meta):
    ok = client.get(
        "/webhooks/meta",
        params={"hub.mode": "subscribe", "hub.verify_token": "karigar-verify", "hub.challenge": "1158201444"},
    )
    assert ok.status_code == 200 and ok.text == "1158201444"
    bad = client.get(
        "/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "x"}
    )
    assert bad.status_code == 403


def test_meta_message_runs_the_flow_and_checks_signature(client, meta):
    code = pune_order(client)["order"]["code"]
    h = login(client, SHINDE)
    assert meta_post(client, meta_payload(SHINDE, "1", "wamid.sig-bad"), secret="wrong").status_code == 403
    assert meta_post(client, meta_payload(SHINDE, "1", "wamid.sig-none"), sign=False).status_code == 403
    assert client.get(f"/api/orders/{code}", headers=h).json()["status"] == "awaiting_maker"  # nothing happened

    r = meta_post(client, meta_payload(SHINDE, "1", "wamid.ok-1"))
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get(f"/api/orders/{code}", headers=h).json()["status"] == "approved"


def test_meta_duplicate_delivery_is_handled_once(client, meta):
    first = pune_order(client)["order"]["code"]
    second = pune_order(client, [{"size": 6, "qty": 25}])["order"]["code"]
    h = login(client, SHINDE)
    payload = meta_payload(SHINDE, "1", "wamid.dup-1")
    meta_post(client, payload)
    meta_post(client, payload)  # Meta retried the same message
    statuses = {code: client.get(f"/api/orders/{code}", headers=h).json()["status"] for code in (first, second)}
    assert statuses == {first: "approved", second: "awaiting_maker"}


def test_meta_receipts_ignored_and_voice_note_asks_for_text(client, meta):
    receipt = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {"statuses": [{"id": "wamid.x", "status": "read", "recipient_id": RETAILER}]},
                    }
                ]
            }
        ],
    }
    assert meta_post(client, receipt).json() == {"ok": True}

    meta_post(client, meta_payload(RETAILER, msg_id="wamid.voice-1", kind="audio"))
    login(client, SHINDE)
    from sqlmodel import Session, select

    from app.core.models import Message

    with Session(engine) as s:
        msgs = s.exec(select(Message).where(Message.phone == RETAILER).order_by(Message.id)).all()
    assert [m.direction for m in msgs] == ["in", "out"] and msgs[0].body == "[audio message]"
    assert "कृपया तुमचा संदेश टाइप करा" in msgs[1].body  # Marathi shop


def test_meta_send_request(client, monkeypatch):
    from app.services import notify

    calls = []

    class R:
        status_code = 200
        text = "{}"

    monkeypatch.setattr(config, "META_WHATSAPP_TOKEN", "EAAtest")
    monkeypatch.setattr(config, "META_PHONE_NUMBER_ID", "123456")
    monkeypatch.setattr(notify.httpx, "post", lambda url, **kw: (calls.append((url, kw)), R())[1])
    assert config.whatsapp_provider() == "meta"

    code = pune_order(client)["order"]["code"]  # sends the approval request to the maker
    url, kw = calls[-1]
    assert url == f"https://graph.facebook.com/{config.META_GRAPH_VERSION}/123456/messages"
    assert kw["headers"]["Authorization"] == "Bearer EAAtest"
    assert kw["json"]["to"] == SHINDE and kw["json"]["type"] == "text"
    assert code in kw["json"]["text"]["body"]

    R.status_code, R.text = 401, '{"error":{"message":"Session has expired"}}'  # expired token
    assert notify._meta_send(RETAILER, "hi") is False
    monkeypatch.setattr(config, "WHATSAPP_PROVIDER", "none")
    assert config.whatsapp_provider() == "none"


# ---------- languages ----------


def test_messages_follow_each_persons_language(client):
    """Hindi shop gets Hindi; English shop gets English; maker switched to English gets English."""
    from sqlmodel import Session, select

    from app.core.models import Message

    def last_to(phone):
        with Session(engine) as s:
            return (
                s.exec(
                    select(Message)
                    .where(Message.phone == phone, Message.direction == "out")
                    .order_by(Message.id.desc())
                )
                .first()
                .body
            )

    hindi = {
        "maker_id": 1,
        "product_code": "classic",
        "retailer_name": "Indore Juti Ghar",
        "retailer_phone": "919811110003",
        "city": "Indore",
        "language": "Hindi",
        "lines": [{"size": 8, "qty": 30}],
    }
    code = client.post("/internal/orders", json=hindi, headers=INTERNAL).json()["order"]["code"]
    assert last_to(SHINDE).startswith(f"नवीन बल्क ऑर्डर {code}")  # maker: Marathi
    client.post("/internal/simulate-message", json={"phone": SHINDE, "body": "1"}, headers=INTERNAL)
    msg = last_to("919811110003")
    assert "कन्फ़र्म" in msg and "नवंबर" in msg  # shop: Hindi

    h = login(client, SHINDE)
    client.patch("/api/me", json={"language": "English"}, headers=h)
    english = {**hindi, "retailer_name": "Mumbai Craft Co.", "retailer_phone": "919811110002", "language": "English"}
    code2 = client.post("/internal/orders", json=english, headers=INTERNAL).json()["order"]["code"]
    assert last_to(SHINDE).startswith(f"New bulk order {code2}")  # maker now English
    client.post(f"/api/orders/{code2}/reject", json={"reason": "No leather"}, headers=h)
    assert last_to("919811110002").startswith(
        "Sorry, Kolhapur Chappal Kendra can't take order"
    ) and "Reason: No leather" in last_to("919811110002")
    assert client.patch("/api/me", json={"language": "French"}, headers=h).status_code == 409


def test_unknown_number_language_is_guessed():
    from app.whatsapp import messages as i18n

    assert i18n.detect("मला क्लासिक 50 जोड्या हव्यात") == "Marathi"
    assert i18n.detect("मुझे कापशी 40 जोड़ी चाहिए") == "Hindi"
    assert i18n.detect("Bhai 30 pair paytan chahiye") == "Hindi"
    assert i18n.detect("mala 50 jodya pahije") == "Marathi"
    assert i18n.detect("Hello, I need 50 pairs") == "English"


def test_all_languages_have_the_same_placeholders():
    import string

    from app.whatsapp import messages as i18n

    for key, texts in i18n.TEXTS.items():
        assert set(texts) == set(i18n.LANGS), key
        fields = [{f for _, f, _, _ in string.Formatter().parse(v) if f} for v in texts.values()]
        assert all(f == fields[0] for f in fields), key


def test_whatsapp_formatting():
    from app.agents.base import whatsapp_format

    assert whatsapp_format("- **KS-1039**: Nashik, __soon__") == "- *KS-1039*: Nashik, _soon_"
    assert whatsapp_format("## Orders\nKS-1041") == "Orders\nKS-1041"
    assert whatsapp_format("*already fine*") == "*already fine*"


def test_agent_survives_bad_history_and_errors(client, monkeypatch):
    """Saved history rejected (400) -> cleared and retried; any other error -> polite reply, no crash."""
    from types import SimpleNamespace as NS

    import anthropic
    from sqlmodel import Session

    from app.core.models import Conversation

    with Session(engine) as s:
        s.add(Conversation(phone="ops:" + SHINDE, history='[{"role": "user", "content": "old"}]'))
        s.commit()

    class Bad(Exception):
        status_code = 400

    calls = {"n": 0}
    text = NS(type="text", text="**Done**")

    class FakeClient:
        def __init__(self, **_):
            self.messages = self

        def create(self, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                assert kw["messages"][0]["content"] == "old"  # first try uses saved history
                raise Bad("bad history")
            assert len(kw["messages"]) == 1  # retry starts fresh
            return NS(stop_reason="end_turn", content=[text])

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "fake")
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    assert maker_says(client, "status?") == "*Done*"

    class Broken:
        def __init__(self, **_):
            self.messages = self

        def create(self, **kw):
            raise RuntimeError("network down")

    monkeypatch.setattr(anthropic, "Anthropic", Broken)
    r = client.post("/internal/simulate-message", json={"phone": SHINDE, "body": "status?"}, headers=INTERNAL)
    assert r.status_code == 200 and "माफ करा" in r.json()["reply"]  # polite Marathi, no 500


def test_thinking_blocks_kept_within_a_reply_but_not_saved(client, monkeypatch):
    """Claude's thinking blocks go back unchanged during tool use, are never stored, and the
    retailer and maker chats of one phone are kept apart (the cause of the 'signature' error)."""
    from types import SimpleNamespace as NS

    import anthropic
    from sqlmodel import Session

    from app.core.models import Conversation

    def thinking():
        return NS(type="thinking", thinking="let me check", signature="SIG-123")

    tool = NS(type="tool_use", id="t1", name="list_orders", input={}, caller={"type": "direct"})
    text = NS(type="text", text="बाकी ऑर्डर नाहीत.", citations=None)
    seen = []

    class FakeClient:
        def __init__(self, **_):
            self.messages = self

        def create(self, **kw):
            seen.append(list(kw["messages"]))
            if len(seen) == 1:
                return NS(stop_reason="tool_use", content=[thinking(), tool])
            return NS(stop_reason="end_turn", content=[text])

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "fake")
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    assert maker_says(client, "आज किती ऑर्डर बाकी आहेत?") == "बाकी ऑर्डर नाहीत."

    second_call = seen[1]
    assistant = second_call[1]["content"]
    assert assistant[0] == {"type": "thinking", "thinking": "let me check", "signature": "SIG-123"}  # unchanged
    assert assistant[1] == {"type": "tool_use", "id": "t1", "name": "list_orders", "input": {}}  # no 'caller'

    with Session(engine) as s:
        saved = s.get(Conversation, "ops:" + SHINDE).history
        assert "SIG-123" not in saved and "list_orders" in saved
        assert s.get(Conversation, SHINDE) is None and s.get(Conversation, "sales:" + SHINDE) is None


def test_my_phones_survive_reset(client, monkeypatch):
    from sqlmodel import Session, select

    from app import seed as seed_mod
    from app.core.models import Maker, Retailer

    monkeypatch.setattr(config, "DEMO_RETAILER_PHONE", "13158865652")
    seed_mod.reset()
    with Session(engine) as s:
        seed_mod.seed(s)
        assert (
            s.exec(select(Maker).where(Maker.name == "Kolhapur Chappal Kendra")).first().phone == SHINDE
        )  # not changed
        assert s.exec(select(Retailer).where(Retailer.name == "Pune Footwear House")).first().phone == "13158865652"
    h = login(client, SHINDE)
    assert client.post("/api/demo/simulate-order", headers=h).json()["retailer_phone"] == "13158865652"


def test_sales_agent_must_ask_which_maker(client, monkeypatch):
    """The Sales Agent sees every maker's designs and is told never to pick a maker for the retailer."""
    seen = fake_claude(monkeypatch, [("text", "कोणत्या कारागिराकडून?")])
    client.post(
        "/internal/simulate-message", json={"phone": RETAILER, "body": "Kolhapuri Classic 50 jodi"}, headers=INTERNAL
    )
    system = seen[0][1]
    assert "Never choose the maker for the retailer" in system
    assert "Kolhapur Chappal Kendra" in system and "Designs: Kolhapuri Classic ₹550" in system


def test_agent_asked_again_when_it_ends_without_text(client, monkeypatch):
    """Claude ending with no text (or cut off by max_tokens) gets one nudge, so the person never sees just '👍'."""
    from types import SimpleNamespace as NS

    import anthropic

    replies = [
        NS(stop_reason="end_turn", content=[]),
        NS(stop_reason="end_turn", content=[NS(type="text", text="ऑर्डर तयार आहे.")]),
    ]
    seen = []

    class FakeClient:
        def __init__(self, **_):
            self.messages = self

        def create(self, **kw):
            seen.append(list(kw["messages"]))
            return replies.pop(0)

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "fake")
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    assert maker_says(client, "status?") == "ऑर्डर तयार आहे."
    assert "Write your WhatsApp reply" in seen[1][-1]["content"][-1]["text"]

    cut = NS(type="tool_use", id="t9", name="list_orders", input={})
    replies[:] = [
        NS(stop_reason="max_tokens", content=[cut]),
        NS(stop_reason="end_turn", content=[NS(type="text", text="ठीक आहे.")]),
    ]
    seen.clear()
    assert maker_says(client, "status?") == "ठीक आहे."
    assert all(
        b.get("type") != "tool_use"
        for m in seen[1]
        if isinstance(m["content"], list)
        for b in m["content"]
        if isinstance(b, dict)
    )  # cut-off tool call not sent back

    replies[:] = [NS(stop_reason="end_turn", content=[]), NS(stop_reason="end_turn", content=[])]
    assert "माफ करा" in maker_says(client, "status?")  # still nothing: polite message


def test_prompt_caching_marks_tools_system_and_last_message(client, monkeypatch):
    """Cache breakpoints on the tools, the system prompt and the latest message; stored history stays plain."""
    from types import SimpleNamespace as NS

    import anthropic
    from sqlmodel import Session

    from app.core.models import Conversation

    calls = []
    tool = NS(type="tool_use", id="t1", name="list_orders", input={})
    replies = [
        NS(stop_reason="tool_use", content=[tool]),
        NS(stop_reason="end_turn", content=[NS(type="text", text="काही नाही.")]),
    ]

    class FakeClient:
        def __init__(self, **_):
            self.messages = self

        def create(self, **kw):
            calls.append(kw)
            return replies.pop(0)

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "fake")
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    maker_says(client, "orders?")
    for kw in calls:
        assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert kw["tools"][-1]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in kw["tools"][0] or len(kw["tools"]) == 1
        assert kw["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert calls[1]["messages"][-1]["content"][-1]["type"] == "tool_result"  # moves forward each step
    with Session(engine) as s:
        assert "cache_control" not in s.get(Conversation, "ops:" + SHINDE).history  # not saved


def test_maker_adds_a_design_on_whatsapp_with_the_websites_rules(client):
    """Operations Agent tool add_design: same checks as the website form, stock starts at 0, audit log entry."""
    from sqlmodel import Session, select

    from app.agents import operations
    from app.core.models import AuditLog, Maker, Product, Stock

    with Session(engine) as s:
        maker = s.exec(select(Maker).where(Maker.phone == SHINDE)).one()
        r = operations.run_tool(
            s, maker, "add_design", {"name": "Kolhapuri Kapshi Gold", "price_per_pair": 700}, "navin design add kar"
        )
        assert r["done"] and r["design_code"] == "kolhapuri-kapshi-gold" and r["sizes"] == [6, 7, 8, 9, 10]
        p = s.exec(select(Product).where(Product.maker_id == maker.id, Product.code == "kolhapuri-kapshi-gold")).one()
        assert (p.price_per_pair, p.pairs_per_day) == (700, 5)
        assert {st.ready for st in s.exec(select(Stock).where(Stock.product_id == p.id))} == {0}
        assert s.exec(select(AuditLog).where(AuditLog.action == "product.added")).first()

        # the same rules as the website: no duplicates, no bad prices or sizes
        dup = operations.run_tool(s, maker, "add_design", {"name": "kolhapuri kapshi gold", "price_per_pair": 650}, "x")
        assert "already have" in dup["error"]
        bad = operations.run_tool(s, maker, "add_design", {"name": "Gents", "price_per_pair": 0}, "x")
        assert "Price per pair" in bad["error"]
        listed = operations.run_tool(
            s, maker, "add_design", {"name": "Bridal", "price_per_pair": 900, "sizes": [5, 6, 7]}, "x"
        )
        assert listed["sizes"] == [5, 6, 7]
