"""Maker (supplier) sessions, and the internal key used by the agent and webhook.
Sign-up, email + password login and admin approval are in accounts.py."""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session, select

from . import config
from .db import get_session
from .models import AccountStatus, Maker, MakerSession, SupplierAccount


def clean_phone(raw: str) -> str:
    """'whatsapp:+91 98000-00001' -> '919800000001'. Adds 91 to 10-digit Indian numbers."""
    digits = re.sub(r"\D", "", raw or "")
    return "91" + digits if len(digits) == 10 else digits


def find_maker(session: Session, phone: str) -> Maker | None:
    return session.exec(select(Maker).where(Maker.phone == clean_phone(phone))).first()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def naive_utc(dt: datetime) -> datetime:
    """SQLite gives back naive datetimes, PostgreSQL aware ones: compare both as naive UTC."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def issue_token(session: Session, maker: Maker) -> str:
    token = secrets.token_urlsafe(32)
    session.add(MakerSession(token=token_hash(token), maker_id=maker.id))
    session.commit()
    return token


def end_session(session: Session, token: str) -> None:
    row = session.get(MakerSession, token_hash(token)) if token else None
    if row:
        session.delete(row)
        session.commit()


def current_maker(authorization: str = Header(default=""), session: Session = Depends(get_session)) -> Maker:
    """The logged-in maker, from the 'Authorization: Bearer <token>' header. Sessions expire after
    SUPPLIER_SESSION_DAYS, and stop working at once if the account is rejected."""
    token = authorization.removeprefix("Bearer ").strip()
    row = session.get(MakerSession, token_hash(token)) if token else None
    if row and naive_utc(row.created_at) < now_utc() - timedelta(days=config.SUPPLIER_SESSION_DAYS):
        session.delete(row)
        session.commit()
        row = None
    if not row:
        raise HTTPException(401, "Please log in again")
    account = session.exec(select(SupplierAccount).where(SupplierAccount.maker_id == row.maker_id)).first()
    if account and account.status != AccountStatus.approved:
        raise HTTPException(401, "Please log in again")
    return session.get(Maker, row.maker_id)


def internal_only(x_internal_key: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_internal_key, config.INTERNAL_API_KEY):
        raise HTTPException(403, "Internal endpoint")
