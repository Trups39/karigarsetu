"""Supplier sign-up, email + password login, sessions, admin approval and the /docs lock."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from app.core import config
from app.core.db import engine
from app.core.models import Maker, MakerSession, Message, SupplierAccount
from app.main import app

ADMIN = {"X-Requested-With": "KarigarSetu"}
NEW = {
    "name": "Asha Patil",
    "business_name": "Asha Chappal Works",
    "craft": "Kolhapuri footwear",
    "town": "Kolhapur",
    "phone": "98220 12345",
    "email": "Asha@Example.com",
    "password": "goodpass123",
    "confirm_password": "goodpass123",
}


@pytest.fixture()
def client():
    SQLModel.metadata.drop_all(engine)
    from app.api import admin

    admin._admin_fails.clear()
    with TestClient(app) as c:
        yield c


def signup(c, **kw):
    return c.post("/auth/signup", json={**NEW, **kw})


def login(c, email="asha@example.com", password="goodpass123"):
    return c.post("/auth/login", json={"email": email, "password": password})


def bearer(r):
    return {"Authorization": "Bearer " + r.json()["token"]}


def admin_login(c, password="test-admin", email="admin@karigarsetu.co.in"):
    return c.post("/api/admin/login", json={"email": email, "password": password}, headers=ADMIN)


def account_id(email="asha@example.com"):
    with Session(engine) as s:
        return s.exec(select(SupplierAccount).where(SupplierAccount.email == email)).first().id


def approve(c, email="asha@example.com", who=None):
    who = who or c
    admin_login(who)
    r = who.post(f"/api/admin/accounts/{account_id(email)}/approve", headers=ADMIN)
    assert r.status_code == 200, r.text
    who.post("/api/admin/logout", headers=ADMIN)
    return r.json()


def test_signup_pending_then_approved_creates_maker_and_dashboard(client):
    r = signup(client)
    assert r.status_code == 201 and r.json()["status"] == "pending"
    r = login(client)
    assert r.status_code == 403 and "under review" in r.json()["detail"]

    acc = approve(client)
    assert acc["status"] == "approved" and acc["phone"] == "919822012345"
    with Session(engine) as s:
        maker = s.get(Maker, acc["maker_id"])
        assert (maker.name, maker.phone, maker.place) == ("Asha Chappal Works", "919822012345", "Kolhapur")
        sent = s.exec(select(Message).where(Message.phone == "919822012345")).all()
        assert any("Asha Chappal Works" in m.body for m in sent)  # WhatsApp "you're approved"

    r = login(client, email="ASHA@example.com")
    assert r.status_code == 200
    h = bearer(r)
    assert client.get("/api/me", headers=h).json()["name"] == "Asha Chappal Works"
    assert client.get("/api/orders", headers=h).json() == []  # only their own orders
    assert client.get("/api/overview", headers=h).status_code == 200


def test_approval_links_existing_maker_by_whatsapp_number(client):
    with Session(engine) as s:
        m = Maker(name="Old Workshop", phone="919822099999", place="Kapshi")
        s.add(m)
        s.commit()
        mid = m.id
    signup(client, phone="+91 98220 99999", email="old@example.com")
    assert approve(client, "old@example.com")["maker_id"] == mid


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("password", "short", "at least 8"),
        ("confirm_password", "different1", "do not match"),
        ("phone", "12345", "valid WhatsApp"),
        ("email", "not-an-email", "valid email"),
        ("business_name", " ", "business name"),
    ],
)
def test_signup_validation(client, field, value, message):
    data = {field: value, **({"confirm_password": value} if field == "password" else {})}
    r = signup(client, **data)
    assert r.status_code == 400 and message in r.json()["detail"]


def test_duplicates_rejected(client):
    assert signup(client).status_code == 201
    assert signup(client, phone="9822000000").status_code == 409  # same email
    assert signup(client, email="b@example.com").status_code == 409  # same phone


def test_wrong_password_is_generic_and_locks_after_5(client):
    signup(client)
    approve(client)
    assert login(client, email="nobody@example.com").json()["detail"] == "Invalid email or password."
    for _ in range(4):
        assert login(client, password="wrongpass1").status_code == 401
    assert login(client, password="wrongpass1").status_code == 429
    assert login(client).status_code == 429  # even the right password, while locked


def test_status_not_revealed_without_right_password(client):
    signup(client)
    r = login(client, password="wrongpass1")
    assert r.status_code == 401 and "review" not in r.json()["detail"]


def test_logout_and_token_stored_hashed(client):
    signup(client)
    approve(client)
    r = login(client)
    token, h = r.json()["token"], bearer(r)
    with Session(engine) as s:
        assert s.get(MakerSession, token) is None  # only the hash is stored
    assert client.get("/api/me", headers=h).status_code == 200
    assert client.post("/auth/logout", headers=h).status_code == 200
    assert client.get("/api/me", headers=h).status_code == 401


def test_session_expires(client, monkeypatch):
    signup(client)
    approve(client)
    h = bearer(login(client))
    monkeypatch.setattr(config, "SUPPLIER_SESSION_DAYS", 0)
    assert client.get("/api/me", headers=h).status_code == 401


def test_reject_logs_out_and_blocks_login(client):
    signup(client)
    approve(client)
    h = bearer(login(client))
    with TestClient(app) as admin:  # the admin uses another browser
        admin_login(admin)
        assert admin.post(f"/api/admin/accounts/{account_id()}/reject", headers=ADMIN).status_code == 200
    assert client.get("/api/me", headers=h).status_code == 401
    r = login(client)
    assert r.status_code == 403 and "wasn't approved" in r.json()["detail"]


def test_sample_suppliers_loaded_by_sql_and_my_signup_survives_reset(client):
    """seed.sql loads the sample makers as approved suppliers (no website login). Your own sign-up is not
    preset; once approved it survives python -m app.seed --reset and gets its maker back."""
    from app import seed as seed_mod

    admin_login(client)
    data = client.get("/api/admin/accounts?status=approved").json()
    assert {a["business_name"] for a in data["accounts"]} == {"Kolhapur Chappal Kendra", "Patil Chappal Udyog"}
    assert all(a["maker_id"] for a in data["accounts"])
    client.post("/api/admin/logout", headers=ADMIN)
    assert login(client, email="kendra@sample.karigarsetu.in", password="sample-no-login").status_code == 401
    assert signup(client, phone="919800000001", email="x@example.com").status_code == 409  # sample's number

    signup(client, phone="917030317109", email="me@example.com", business_name="My Workshop")
    approve(client, "me@example.com")
    assert login(client, email="me@example.com").json()["maker"]["name"] == "My Workshop"

    assert seed_mod.reset() == 1  # only my login is kept; samples come from SQL
    with Session(engine) as s:
        seed_mod.seed(s)
        assert len(s.exec(select(SupplierAccount)).all()) == 3
    r = login(client, email="me@example.com")
    assert r.status_code == 200 and r.json()["maker"]["name"] == "My Workshop"
    assert client.get("/api/me", headers=bearer(r)).json()["phone"] == "917030317109"


def test_admin_api_needs_admin_and_header(client):
    signup(client)
    assert client.get("/api/admin/accounts").status_code == 401
    assert client.post(f"/api/admin/accounts/{account_id()}/approve", headers=ADMIN).status_code == 401
    assert client.post("/api/admin/login", json={"password": "test-admin"}).status_code == 403  # no header
    assert admin_login(client, "wrong").status_code == 401
    assert admin_login(client, email="someone@else.com").status_code == 401  # wrong email
    assert admin_login(client, email="ADMIN@karigarsetu.co.in").status_code == 200  # any case
    client.post("/api/admin/logout", headers=ADMIN)
    assert admin_login(client).status_code == 200
    data = client.get("/api/admin/accounts?status=pending").json()
    assert data["counts"]["pending"] == 1 and data["accounts"][0]["email"] == "asha@example.com"
    assert client.post(f"/api/admin/accounts/{account_id()}/approve").status_code == 403  # no header
    assert client.get("/admin").status_code == 200


def test_admin_login_rate_limited(client):
    for _ in range(5):
        assert admin_login(client, "wrong").status_code == 401
    assert admin_login(client).status_code == 429


def test_admin_off_without_password(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    assert admin_login(client).status_code == 503
    assert client.get("/docs").status_code == 200  # local laptop: docs stay open


def test_docs_admin_only_when_password_set(client):
    r = client.get("/docs", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    assert client.get("/openapi.json").status_code == 401
    admin_login(client)
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_one_login_per_browser(client):
    signup(client)
    with TestClient(app) as other:
        approve(client, who=other)
    admin_login(client)
    assert client.get("/api/admin/accounts").status_code == 200
    assert login(client).status_code == 200
    assert client.get("/api/admin/accounts").status_code == 401  # supplier login ended the admin session


def test_webhooks_and_internal_unaffected(client):
    """WhatsApp and the agent's internal endpoints keep working without any login."""
    r = client.post(
        "/internal/simulate-message",
        json={"phone": "919800000001", "body": "hello"},
        headers={"X-Internal-Key": "test-key"},
    )
    assert r.status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/public/makers").status_code == 200


def test_makers_start_empty_and_new_maker_adds_designs(client, monkeypatch):
    """Normal setup: no makers until a sign-up is approved; the new maker adds designs and can take orders."""
    from app import seed as seed_mod
    from app.core.models import Retailer

    monkeypatch.setattr(config, "SAMPLE_MAKERS", False)
    seed_mod.reset()
    with Session(engine) as s:
        seed_mod.seed(s)
        assert s.exec(select(Maker)).first() is None
        assert s.exec(select(Retailer)).first() is not None  # shops are still loaded

    signup(client)
    approve(client)
    h = bearer(login(client))
    assert client.post("/api/demo/simulate-order", headers=h).status_code == 409  # no designs yet
    r = client.post(
        "/api/products",
        headers=h,
        json={"name": "Kolhapuri Classic", "price_per_pair": 550, "pairs_per_day": 6, "sizes": "6, 7, 8, 9, 10"},
    )
    assert r.status_code == 201 and r.json()["code"] == "kolhapuri-classic"
    assert (
        client.post("/api/products", headers=h, json={"name": "kolhapuri classic", "price_per_pair": 1}).status_code
        == 409
    )
    assert (
        client.post(
            "/api/products", headers=h, json={"name": "Kapshi", "price_per_pair": 600, "sizes": "x"}
        ).status_code
        == 400
    )
    client.put("/api/stock", headers=h, json={"product_code": "kolhapuri-classic", "size": 8, "ready": 10})
    o = client.post("/api/demo/simulate-order", headers=h).json()
    assert o["product_code"] == "kolhapuri-classic" and o["status"] == "awaiting_maker"
