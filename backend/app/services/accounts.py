"""Supplier accounts: passwords, admin sessions, approving/rejecting suppliers, and keeping each account
linked to its maker. No HTTP here: the routes are in api/accounts.py and api/admin.py.

Flow: a maker signs up -> account "pending" -> the KarigarSetu team approves it at /admin
-> a Maker is created (or linked by WhatsApp number) -> the maker logs in and gets their dashboard.
"""

import logging
from datetime import timedelta
from typing import Optional

import bcrypt
from fastapi import Request, Response
from sqlmodel import Session, select

from ..core import config
from ..core.models import AccountStatus, AdminSession, Maker, MakerSession, SupplierAccount, utcnow
from ..core.security import naive_utc, now_utc, token_hash
from ..whatsapp import messages as i18n
from . import audit, notify

log = logging.getLogger("karigarsetu.accounts")

ADMIN_COOKIE = "ks_admin"
PENDING = "Your account is under review. We'll message you on WhatsApp once it's approved."


# ---------- passwords ----------


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=config.BCRYPT_ROUNDS)).decode()


def password_ok(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw((password or "").encode(), hashed.encode())
    except ValueError:  # malformed hash, or password longer than 72 bytes
        return False


_DUMMY: list[str] = []


def dummy_hash() -> str:
    """Checked when the email doesn't exist, so the response time doesn't reveal which emails are registered."""
    if not _DUMMY:
        _DUMMY.append(hash_password("not-a-real-password"))
    return _DUMMY[0]


def account_view(a: SupplierAccount) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "business_name": a.business_name,
        "craft": a.craft,
        "town": a.town,
        "phone": a.phone,
        "email": a.email,
        "status": a.status,
        "maker_id": a.maker_id,
        "created_at": a.created_at,
        "reviewed_at": a.reviewed_at,
    }


# ---------- admin sessions (httpOnly cookie) ----------


def _admin_token_ok(session: Session, token: Optional[str]) -> bool:
    if not token or not config.ADMIN_PASSWORD:
        return False
    row = session.get(AdminSession, token_hash(token))
    if row and naive_utc(row.created_at) < now_utc() - timedelta(hours=config.ADMIN_SESSION_HOURS):
        session.delete(row)
        session.commit()
        return False
    return row is not None


def is_admin(request: Request, session: Session) -> bool:
    return _admin_token_ok(session, request.cookies.get(ADMIN_COOKIE))


def end_admin_session(request: Request, response: Response, session: Session) -> None:
    token = request.cookies.get(ADMIN_COOKIE)
    if token:
        row = session.get(AdminSession, token_hash(token))
        if row:
            session.delete(row)
            session.commit()
        response.delete_cookie(ADMIN_COOKIE, path="/")


# ---------- approving and rejecting ----------


def approve_account(session: Session, a: SupplierAccount) -> SupplierAccount:
    """Link to the maker with this WhatsApp number, or create one. Then tell them on WhatsApp."""
    was = a.status
    maker = session.get(Maker, a.maker_id) if a.maker_id else None
    maker = maker or session.exec(select(Maker).where(Maker.phone == a.phone)).first()
    if not maker:
        maker = Maker(name=a.business_name, phone=a.phone, place=a.town)
        session.add(maker)
        session.flush()
    a.maker_id, a.status, a.reviewed_at = maker.id, AccountStatus.approved, utcnow()
    session.add(a)
    session.commit()
    audit.log(session, "System", "account.approved", f"{a.business_name} ({a.email}) approved", maker.id)
    if was != AccountStatus.approved:
        notify.send(
            session, maker.phone, i18n.t("account_approved", maker.language, name=a.name, business=a.business_name)
        )
        session.commit()
    return a


def reject_account(session: Session, a: SupplierAccount) -> SupplierAccount:
    a.status, a.reviewed_at = AccountStatus.rejected, utcnow()
    session.add(a)
    if a.maker_id:  # log them out everywhere
        for s in session.exec(select(MakerSession).where(MakerSession.maker_id == a.maker_id)):
            session.delete(s)
    session.commit()
    audit.log(session, "System", "account.rejected", f"{a.business_name} ({a.email}) rejected", a.maker_id)
    return a


# ---------- emails about an account (to the supplier and to the KarigarSetu team) ----------

SAMPLE_EMAIL_DOMAIN = "@sample.karigarsetu.in"  # the sample suppliers' made-up addresses: never emailed


def account_emails(kind: str, a: SupplierAccount) -> list[tuple[Optional[str], str, str]]:
    """Emails to send when an account is signed up, approved or rejected: (to, subject, body).
    to=None means the team mailbox (CONTACT_TO). Plain text, sent in the background by the API."""
    site, support = config.PUBLIC_URL, config.SUPPORT_EMAIL
    details = (
        f"Name:     {a.name}\nBusiness: {a.business_name}\nCraft:    {a.craft}\nTown:     {a.town}\n"
        f"WhatsApp: +{a.phone}\nEmail:    {a.email}\n"
    )
    sign = f"\n\nTeam KarigarSetu\n{site}\n"
    if kind == "signup":
        team = (
            f"New supplier waiting for approval: {a.business_name}",
            f"{a.name} signed up as a supplier on KarigarSetu.\n\n{details}\nApprove or reject: {site}/admin\n",
        )
        maker = (
            "We received your KarigarSetu application",
            f"Namaste {a.name},\n\nThank you for applying to sell on KarigarSetu as {a.business_name}. "
            "Our team will review your details soon. You'll get an email and a WhatsApp message "
            f"on +{a.phone} once your account is approved.\n\nQuestions? Write to {support}.{sign}",
        )
    elif kind == "approved":
        team = (f"Supplier approved: {a.business_name}", f"This supplier was approved on /admin.\n\n{details}")
        maker = (
            "Your KarigarSetu account is approved",
            f"Namaste {a.name},\n\nGood news: {a.business_name} is approved on KarigarSetu.\n\n"
            f"Log in at {site} (Supplier login) with {a.email} and your password, then:\n"
            "1. Add your designs and prices (Products)\n"
            "2. Add the pairs you have ready (Stock)\n\n"
            "Shops can then order from you on WhatsApp, and you approve every order with one reply."
            f"\n\nQuestions? Write to {support}.{sign}",
        )
    elif kind == "rejected":
        team = (f"Supplier rejected: {a.business_name}", f"This supplier was rejected on /admin.\n\n{details}")
        maker = (
            "About your KarigarSetu application",
            f"Namaste {a.name},\n\nThank you for applying to KarigarSetu as {a.business_name}. "
            "We couldn't approve your application this time.\n\n"
            f"If you think this is a mistake or would like to share more details, write to {support} "
            f"and we'll take another look.{sign}",
        )
    else:
        raise ValueError(kind)
    out: list[tuple[Optional[str], str, str]] = [(None, *team)]
    if a.email and not a.email.endswith(SAMPLE_EMAIL_DOMAIN):
        out.append((a.email, *maker))
    return out


# ---------- keep accounts linked to their maker (after a reset, the makers are recreated) ----------


def relink_accounts(session: Session) -> int:
    """Every approved account points at the maker with its WhatsApp number (created if missing).
    So if you sign up with Kolhapur Chappal Kendra's number, you get Kolhapur Chappal Kendra's orders and stock."""
    n = 0
    for a in session.exec(select(SupplierAccount)).all():
        maker = session.exec(select(Maker).where(Maker.phone == a.phone)).first()
        if a.status == AccountStatus.approved and not maker:
            maker = Maker(name=a.business_name, phone=a.phone, place=a.town)
            session.add(maker)
            session.flush()
        new_id = maker.id if (maker and a.status == AccountStatus.approved) else None
        if a.maker_id != new_id:
            a.maker_id = new_id
            session.add(a)
            n += 1
    session.commit()
    return n
