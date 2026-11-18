"""Supplier accounts: sign-up, email + password login, logout, and admin approval.

Flow: a maker signs up on the website -> account is "pending" -> the KarigarSetu team approves it at /admin
-> a Maker is created (or linked by WhatsApp number) -> the maker can log in and gets their dashboard.

Suppliers use a Bearer token (stored by the website). The admin uses an httpOnly cookie, and only one
of the two can be logged in per browser at a time.
"""
import hmac
import logging
import math
import re
import secrets
import time
from datetime import timedelta
from pathlib import Path
from typing import Optional

import bcrypt
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from . import config, i18n
from .auth import end_session, issue_token, naive_utc, now_utc, token_hash
from .db import get_session
from .models import AccountStatus, AdminSession, Maker, MakerSession, SupplierAccount, utcnow
from . import validation as V
from .services import audit, mailer, notify

log = logging.getLogger("karigarsetu.accounts")
router = APIRouter()

ADMIN_COOKIE = "ks_admin"
PENDING = "Your account is under review. We'll message you on WhatsApp once it's approved."
ADMIN_PAGE = Path(__file__).resolve().parents[2] / "frontend" / "admin.html"

# ---------- passwords ----------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=config.BCRYPT_ROUNDS)).decode()


def password_ok(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw((password or "").encode(), hashed.encode())
    except ValueError:   # malformed hash, or password longer than 72 bytes
        return False


_DUMMY: list[str] = []


def _dummy_hash() -> str:
    """Checked when the email doesn't exist, so the response time doesn't reveal which emails are registered."""
    if not _DUMMY:
        _DUMMY.append(hash_password("not-a-real-password"))
    return _DUMMY[0]


# ---------- validation: shared rules in validation.py ----------

def _phone(raw: str) -> str:   # kept for older imports
    return V.whatsapp(raw)


def account_view(a: SupplierAccount) -> dict:
    return {"id": a.id, "name": a.name, "business_name": a.business_name, "craft": a.craft, "town": a.town,
            "phone": a.phone, "email": a.email, "status": a.status, "maker_id": a.maker_id,
            "created_at": a.created_at, "reviewed_at": a.reviewed_at}


# ---------- request bodies ----------

class SignupIn(BaseModel):
    name: str = ""
    business_name: str = ""
    craft: str = ""
    town: str = ""
    phone: str = ""
    email: str = ""
    password: str = ""
    confirm_password: str = ""


class LoginIn(BaseModel):
    email: str = ""
    password: str = ""


class AdminLoginIn(BaseModel):
    email: str = ""
    password: str = ""


# ---------- supplier: sign up, log in, log out ----------

@router.post("/auth/signup", status_code=201, tags=["supplier login"])
def signup(body: SignupIn, background: BackgroundTasks, session: Session = Depends(get_session)):
    a = SupplierAccount(name=V.person_name(body.name), business_name=V.business_name(body.business_name),
                        craft=V.place_or_craft(body.craft, "craft"), town=V.place_or_craft(body.town, "town or city"),
                        phone=V.whatsapp(body.phone), email=V.email(body.email), password_hash="")
    V.new_password(body.password, a.email)
    if body.password != body.confirm_password:
        raise HTTPException(400, "Passwords do not match.")
    if session.exec(select(SupplierAccount).where(SupplierAccount.email == a.email)).first():
        raise HTTPException(409, "An account with this email already exists.")
    if session.exec(select(SupplierAccount).where(SupplierAccount.phone == a.phone)).first():
        raise HTTPException(409, "This WhatsApp number is already registered.")
    a.password_hash = hash_password(body.password)
    session.add(a)
    session.commit()
    audit.log(session, "System", "account.signup", f"{a.business_name} ({a.email}) signed up, waiting for approval")
    session.commit()
    # Tell the KarigarSetu team by email (Titan mailbox on our domain); never blocks the sign-up.
    background.add_task(mailer.send_quietly, f"New supplier waiting for approval: {a.business_name}",
                        f"{a.name} signed up as a supplier on KarigarSetu.\n\n"
                        f"Business: {a.business_name}\nCraft:    {a.craft}\nTown:     {a.town}\n"
                        f"WhatsApp: +{a.phone}\nEmail:    {a.email}\n\n"
                        f"Approve or reject: {config.PUBLIC_URL}/admin\n")
    return {"status": a.status, "message": PENDING}


@router.post("/auth/login", tags=["supplier login"])
def login(body: LoginIn, request: Request, response: Response, session: Session = Depends(get_session)):
    """Email + password. Returns a token for 'Authorization: Bearer <token>'."""
    email = (body.email or "").strip().lower()
    a = session.exec(select(SupplierAccount).where(SupplierAccount.email == email)).first()
    if not a:
        password_ok(body.password, _dummy_hash())
        raise HTTPException(401, "Invalid email or password.")
    now = now_utc()
    if a.locked_until and naive_utc(a.locked_until) > now:
        mins = max(1, math.ceil((naive_utc(a.locked_until) - now).total_seconds() / 60))
        raise HTTPException(429, f"Too many failed attempts. Try again in {mins} minute(s).")
    if not password_ok(body.password, a.password_hash):
        a.failed_logins += 1
        locked = a.failed_logins >= config.MAX_FAILED_LOGINS
        if locked:
            a.failed_logins, a.locked_until = 0, utcnow() + timedelta(minutes=config.LOGIN_LOCK_MINUTES)
        session.add(a)
        session.commit()
        if locked:
            raise HTTPException(429, f"Too many failed attempts. Try again in {config.LOGIN_LOCK_MINUTES} minutes.")
        raise HTTPException(401, "Invalid email or password.")
    if a.failed_logins or a.locked_until:
        a.failed_logins, a.locked_until = 0, None
        session.add(a)
        session.commit()
    # The status is only revealed after the right password.
    if a.status == AccountStatus.pending:
        raise HTTPException(403, PENDING)
    if a.status == AccountStatus.rejected or not a.maker_id:
        raise HTTPException(403, f"Your application wasn't approved. Please contact {config.SUPPORT_EMAIL}.")
    maker = session.get(Maker, a.maker_id)
    _end_admin(request, response, session)   # one login per browser
    audit.log(session, "Maker", "login", "", maker.id)
    maker_data, account_data = maker.model_dump(), account_view(a)   # read before the commit expires them
    return {"token": issue_token(session, maker), "maker": maker_data, "account": account_data}


@router.post("/auth/logout", tags=["supplier login"])
def logout(authorization: str = Header(default=""), session: Session = Depends(get_session)):
    end_session(session, authorization.removeprefix("Bearer ").strip())
    return {"ok": True}


# ---------- admin ----------

_admin_fails: dict[str, list[float]] = {}


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


def _end_admin(request: Request, response: Response, session: Session) -> None:
    token = request.cookies.get(ADMIN_COOKIE)
    if token:
        row = session.get(AdminSession, token_hash(token))
        if row:
            session.delete(row)
            session.commit()
        response.delete_cookie(ADMIN_COOKIE, path="/")


def require_admin(request: Request, session: Session = Depends(get_session)) -> None:
    if not is_admin(request, session):
        raise HTTPException(401, "Admin login required.")


def same_site(x_requested_with: str = Header(default="")) -> None:
    """The admin page's own script sends this header; a form on another website can't."""
    if x_requested_with != "KarigarSetu":
        raise HTTPException(403, "Please use the KarigarSetu admin page.")


@router.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(ADMIN_PAGE, headers={"Cache-Control": "no-store"})


@router.post("/api/admin/login", dependencies=[Depends(same_site)], tags=["admin"])
def admin_login(body: AdminLoginIn, request: Request, session: Session = Depends(get_session)):
    if not config.ADMIN_PASSWORD:
        raise HTTPException(503, "Admin login is off. Set ADMIN_PASSWORD in backend/.env and restart.")
    key = request.client.host if request.client else "?"
    now = time.time()
    _admin_fails[key] = [t for t in _admin_fails.get(key, []) if now - t < 900]
    if len(_admin_fails[key]) >= 5:
        raise HTTPException(429, "Too many wrong attempts. Try again in 15 minutes.")
    email_ok = not config.ADMIN_EMAIL or hmac.compare_digest((body.email or "").strip().lower().encode(),
                                                             config.ADMIN_EMAIL.encode())
    password_ok_ = hmac.compare_digest((body.password or "").encode(), config.ADMIN_PASSWORD.encode())
    if not (email_ok and password_ok_):
        _admin_fails[key].append(now)
        raise HTTPException(401, "Wrong admin email or password." if config.ADMIN_EMAIL else "Wrong admin password.")
    _admin_fails.pop(key, None)
    token = secrets.token_urlsafe(32)
    session.add(AdminSession(token=token_hash(token)))
    session.commit()
    resp = JSONResponse({"ok": True})
    resp.set_cookie(ADMIN_COOKIE, token, max_age=config.ADMIN_SESSION_HOURS * 3600, httponly=True,
                    secure=config.COOKIE_SECURE, samesite="lax", path="/")
    return resp


@router.post("/api/admin/logout", dependencies=[Depends(same_site)], tags=["admin"])
def admin_logout(request: Request, response: Response, session: Session = Depends(get_session)):
    _end_admin(request, response, session)
    return {"ok": True}


@router.get("/api/admin/me", tags=["admin"])
def admin_me(request: Request, session: Session = Depends(get_session)):
    return {"admin": is_admin(request, session), "enabled": bool(config.ADMIN_PASSWORD),
            "needs_email": bool(config.ADMIN_EMAIL)}


@router.get("/api/admin/accounts", dependencies=[Depends(require_admin)], tags=["admin"])
def admin_accounts(status: Optional[AccountStatus] = None, session: Session = Depends(get_session)):
    q = select(SupplierAccount).order_by(SupplierAccount.created_at.desc(), SupplierAccount.id.desc())
    if status:
        q = q.where(SupplierAccount.status == status)
    all_ = session.exec(select(SupplierAccount)).all()
    counts = {s.value: sum(1 for a in all_ if a.status == s) for s in AccountStatus}
    return {"accounts": [account_view(a) for a in session.exec(q)], "counts": counts}


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
        notify.send(session, maker.phone, i18n.t("account_approved", maker.language, name=a.name,
                                                 business=a.business_name))
        session.commit()
    return a


def reject_account(session: Session, a: SupplierAccount) -> SupplierAccount:
    a.status, a.reviewed_at = AccountStatus.rejected, utcnow()
    session.add(a)
    if a.maker_id:   # log them out everywhere
        for s in session.exec(select(MakerSession).where(MakerSession.maker_id == a.maker_id)):
            session.delete(s)
    session.commit()
    audit.log(session, "System", "account.rejected", f"{a.business_name} ({a.email}) rejected", a.maker_id)
    return a


def _account(session: Session, account_id: int) -> SupplierAccount:
    a = session.get(SupplierAccount, account_id)
    if not a:
        raise HTTPException(404, "Account not found.")
    return a


@router.post("/api/admin/accounts/{account_id}/approve", dependencies=[Depends(require_admin), Depends(same_site)],
             tags=["admin"])
def admin_approve(account_id: int, session: Session = Depends(get_session)):
    return account_view(approve_account(session, _account(session, account_id)))


@router.post("/api/admin/accounts/{account_id}/reject", dependencies=[Depends(require_admin), Depends(same_site)],
             tags=["admin"])
def admin_reject(account_id: int, session: Session = Depends(get_session)):
    return account_view(reject_account(session, _account(session, account_id)))


# ---------- /docs is admin-only once ADMIN_PASSWORD is set ----------

ADMIN_ONLY_PATHS = ("/docs", "/redoc", "/openapi.json")


async def protect_docs(request: Request, call_next):
    path = request.url.path
    if config.ADMIN_PASSWORD and any(path == p or path.startswith(p + "/") for p in ADMIN_ONLY_PATHS):
        from starlette.concurrency import run_in_threadpool

        from .db import engine

        def check() -> bool:
            with Session(engine) as s:
                return is_admin(request, s)

        if not await run_in_threadpool(check):
            if "text/html" in request.headers.get("accept", ""):
                return RedirectResponse("/admin", status_code=303)
            return JSONResponse({"detail": "Admin login required."}, status_code=401)
    return await call_next(request)


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
