"""Website contact form (Titan email), new-supplier alert email, and the home page's maker list."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from app.api import contact
from app.core import config
from app.core.db import engine
from app.core.models import ContactMessage
from app.main import app
from app.services import mailer

GOOD = {
    "name": "Rahul Patil",
    "email": "Rahul@Shop.in",
    "phone": "+91 98220 11111",
    "message": "We run a footwear shop in Satara and want 100 pairs a month.",
}


@pytest.fixture()
def client():
    SQLModel.metadata.drop_all(engine)
    contact.reset_limits()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sent(monkeypatch):
    """Fake the Titan SMTP server: collect the emails instead of sending them."""
    mails = []

    class FakeSMTP:
        def __init__(self, host, port, **kw):
            self.host, self.port = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, password):
            assert (user, password) == ("contact@karigarsetu.co.in", "secret")

        def send_message(self, msg):
            mails.append(msg)

    monkeypatch.setattr(config, "SMTP_USERNAME", "contact@karigarsetu.co.in")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    return mails


def test_contact_form_emails_the_mailbox_and_saves(client, sent):
    r = client.post("/api/contact", json=GOOD)
    assert r.status_code == 200 and r.json()["ok"]
    assert len(sent) == 1
    m = sent[0]
    assert m["To"] == "contact@karigarsetu.co.in" and m["Reply-To"] == "rahul@shop.in"
    assert "Rahul Patil" in m["Subject"] and "100 pairs a month" in m.get_content()
    with Session(engine) as s:
        row = s.exec(select(ContactMessage)).one()
        assert row.emailed and row.email == "rahul@shop.in"


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("name", "", "name"),
        ("name", "12", "letters"),
        ("name", "<script>", "letters"),
        ("email", "not-an-email", "email"),
        ("email", "a@b.c", "email"),
        ("email", "a..b@shop.in", "email"),
        ("phone", "abc", "digits"),
        ("phone", "12345", "10 to 15"),
        ("message", "hi", "message"),
        ("message", "x" * 2001, "too long"),
    ],
)
def test_contact_form_validation(client, sent, field, value, error):
    r = client.post("/api/contact", json={**GOOD, field: value})
    assert r.status_code == 400 and error in r.json()["detail"]
    assert not sent


def test_contact_form_honeypot_and_rate_limit(client, sent):
    r = client.post("/api/contact", json={**GOOD, "website": "http://spam.example"})
    assert r.status_code == 200 and not sent  # bot: looks fine, nothing sent
    for _ in range(5):
        assert client.post("/api/contact", json=GOOD).status_code == 200
    assert client.post("/api/contact", json=GOOD).status_code == 429


def test_contact_form_without_smtp_still_saves(client, monkeypatch):
    monkeypatch.setattr(config, "SMTP_PASSWORD", "")
    assert client.post("/api/contact", json=GOOD).status_code == 200
    with Session(engine) as s:
        assert not s.exec(select(ContactMessage)).one().emailed


def test_contact_form_email_failure_is_reported(client, monkeypatch, sent):
    def broken(*a, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", broken)
    r = client.post("/api/contact", json=GOOD)
    assert r.status_code == 502 and "contact@karigarsetu.co.in" in r.json()["detail"]


def test_new_supplier_signup_emails_the_team(client, sent, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "https://karigarsetu.co.in")
    r = client.post(
        "/auth/signup",
        json={
            "name": "Asha",
            "business_name": "Asha Chappals",
            "craft": "Kolhapuri",
            "town": "Kolhapur",
            "phone": "9822012345",
            "email": "asha@example.com",
            "password": "goodpass123",
            "confirm_password": "goodpass123",
        },
    )
    assert r.status_code == 201
    assert len(sent) == 1 and "Asha Chappals" in sent[0]["Subject"]
    assert "https://karigarsetu.co.in/admin" in sent[0].get_content()


def test_public_makers_use_the_bot_number(client, monkeypatch):
    monkeypatch.setattr(config, "BOT_WHATSAPP_NUMBER", "15551567876")
    makers = client.get("/public/makers").json()
    assert {m["name"] for m in makers} == {"Kolhapur Chappal Kendra", "Patil Chappal Udyog"}
    for m in makers:
        assert m["whatsapp"].startswith("https://wa.me/15551567876?text=")
        assert m["name"].replace(" ", "%20") in m["whatsapp"]
        assert m["price_from"] == min(d["price_per_pair"] for d in m["designs"])
    assert client.get("/public/info").json() == {"email": "contact@karigarsetu.co.in", "whatsapp": "15551567876"}


def test_public_makers_hide_pending_and_empty_makers(client):
    client.post(
        "/auth/signup",
        json={
            "name": "Asha",
            "business_name": "Asha Chappals",
            "craft": "Kolhapuri",
            "town": "Kolhapur",
            "phone": "9822012345",
            "email": "asha@example.com",
            "password": "goodpass123",
            "confirm_password": "goodpass123",
        },
    )
    names = {m["name"] for m in client.get("/public/makers").json()}
    assert "Asha Chappals" not in names  # pending: no maker yet; approved without designs: hidden


@pytest.mark.parametrize(
    "name,phone", [("तृप्ती भोसले", ""), ("D'Souza-Patil Jr.", "+91 98220-11111"), ("Rahul", "(022) 2345 6789")]
)
def test_contact_form_accepts_real_names_and_phones(client, sent, name, phone):
    assert client.post("/api/contact", json={**GOOD, "name": name, "phone": phone}).status_code == 200
