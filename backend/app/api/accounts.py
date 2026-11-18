"""Supplier sign-up, login and logout (website). Logic: services/accounts.py, field rules: services/validation.py."""
import math
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..core import config
from ..core.db import get_session
from ..core.models import AccountStatus, Maker, SupplierAccount, utcnow
from ..core.security import end_session, issue_token, naive_utc, now_utc
from ..services import audit, mailer
from ..services import validation as V
from ..services.accounts import PENDING, dummy_hash, end_admin_session, account_view, hash_password, password_ok

router = APIRouter(tags=["supplier login"])


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


@router.post("/auth/signup", status_code=201)
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


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, session: Session = Depends(get_session)):
    """Email + password. Returns a token for 'Authorization: Bearer <token>'."""
    email = (body.email or "").strip().lower()
    a = session.exec(select(SupplierAccount).where(SupplierAccount.email == email)).first()
    if not a:
        password_ok(body.password, dummy_hash())
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
    end_admin_session(request, response, session)   # one login per browser
    audit.log(session, "Maker", "login", "", maker.id)
    maker_data, account_data = maker.model_dump(), account_view(a)   # read before the commit expires them
    return {"token": issue_token(session, maker), "maker": maker_data, "account": account_data}


@router.post("/auth/logout")
def logout(authorization: str = Header(default=""), session: Session = Depends(get_session)):
    end_session(session, authorization.removeprefix("Bearer ").strip())
    return {"ok": True}
