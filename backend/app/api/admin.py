"""Admin page and API (/admin): approve or reject new suppliers. Also keeps /docs admin-only.

The admin logs in with ADMIN_EMAIL + ADMIN_PASSWORD and gets an httpOnly cookie. Changes need the
X-Requested-With: KarigarSetu header, which a form on another website can't send.
"""

import hmac
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from ..core import config
from ..core.db import get_session
from ..core.models import AccountStatus, AdminSession, SupplierAccount
from ..core.security import token_hash
from ..services import mailer
from ..services.accounts import (
    ADMIN_COOKIE,
    account_emails,
    account_view,
    approve_account,
    end_admin_session,
    is_admin,
    reject_account,
)

router = APIRouter()
ADMIN_PAGE = Path(__file__).resolve().parents[3] / "frontend" / "admin.html"  # karigarsetu/frontend/admin.html
_admin_fails: dict[str, list[float]] = {}


class AdminLoginIn(BaseModel):
    email: str = ""
    password: str = ""


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
    email_ok = not config.ADMIN_EMAIL or hmac.compare_digest(
        (body.email or "").strip().lower().encode(), config.ADMIN_EMAIL.encode()
    )
    password_ok_ = hmac.compare_digest((body.password or "").encode(), config.ADMIN_PASSWORD.encode())
    if not (email_ok and password_ok_):
        _admin_fails[key].append(now)
        raise HTTPException(401, "Wrong admin email or password." if config.ADMIN_EMAIL else "Wrong admin password.")
    _admin_fails.pop(key, None)
    token = secrets.token_urlsafe(32)
    session.add(AdminSession(token=token_hash(token)))
    session.commit()
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        ADMIN_COOKIE,
        token,
        max_age=config.ADMIN_SESSION_HOURS * 3600,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return resp


@router.post("/api/admin/logout", dependencies=[Depends(same_site)], tags=["admin"])
def admin_logout(request: Request, response: Response, session: Session = Depends(get_session)):
    end_admin_session(request, response, session)
    return {"ok": True}


@router.get("/api/admin/me", tags=["admin"])
def admin_me(request: Request, session: Session = Depends(get_session)):
    return {
        "admin": is_admin(request, session),
        "enabled": bool(config.ADMIN_PASSWORD),
        "needs_email": bool(config.ADMIN_EMAIL),
    }


@router.get("/api/admin/accounts", dependencies=[Depends(require_admin)], tags=["admin"])
def admin_accounts(status: Optional[AccountStatus] = None, session: Session = Depends(get_session)):
    q = select(SupplierAccount).order_by(SupplierAccount.created_at.desc(), SupplierAccount.id.desc())
    if status:
        q = q.where(SupplierAccount.status == status)
    all_ = session.exec(select(SupplierAccount)).all()
    counts = {s.value: sum(1 for a in all_ if a.status == s) for s in AccountStatus}
    return {"accounts": [account_view(a) for a in session.exec(q)], "counts": counts}


def _account(session: Session, account_id: int) -> SupplierAccount:
    a = session.get(SupplierAccount, account_id)
    if not a:
        raise HTTPException(404, "Account not found.")
    return a


@router.post(
    "/api/admin/accounts/{account_id}/approve",
    dependencies=[Depends(require_admin), Depends(same_site)],
    tags=["admin"],
)
def admin_approve(account_id: int, background: BackgroundTasks, session: Session = Depends(get_session)):
    a = _account(session, account_id)
    was = a.status
    a = approve_account(session, a)
    if was != AccountStatus.approved:
        _email(background, "approved", a)
    return account_view(a)


@router.post(
    "/api/admin/accounts/{account_id}/reject", dependencies=[Depends(require_admin), Depends(same_site)], tags=["admin"]
)
def admin_reject(account_id: int, background: BackgroundTasks, session: Session = Depends(get_session)):
    a = _account(session, account_id)
    was = a.status
    a = reject_account(session, a)
    if was != AccountStatus.rejected:
        _email(background, "rejected", a)
    return account_view(a)


def _email(background: BackgroundTasks, kind: str, a: SupplierAccount) -> None:
    """Email the supplier and the team after the response is sent; a mail problem never fails the action."""
    for to, subject, text in account_emails(kind, a):
        background.add_task(mailer.send_quietly, subject, text, to=to)


# ---------- /docs is admin-only once ADMIN_PASSWORD is set ----------

ADMIN_ONLY_PATHS = ("/docs", "/redoc", "/openapi.json")


async def protect_docs(request: Request, call_next):
    path = request.url.path
    if config.ADMIN_PASSWORD and any(path == p or path.startswith(p + "/") for p in ADMIN_ONLY_PATHS):
        from starlette.concurrency import run_in_threadpool

        from ..core.db import engine

        def check() -> bool:
            with Session(engine) as s:
                return is_admin(request, s)

        if not await run_in_threadpool(check):
            if "text/html" in request.headers.get("accept", ""):
                return RedirectResponse("/admin", status_code=303)
            return JSONResponse({"detail": "Admin login required."}, status_code=401)
    return await call_next(request)
