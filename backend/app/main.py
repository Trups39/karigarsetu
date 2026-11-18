"""KarigarSetu API.   Run (from backend/):  python -m uvicorn app.main:app --reload     Docs: /docs

This file only puts the app together. The code lives in:
    core/      settings, database, tables, sessions
    api/       HTTP endpoints, one module per area
    agents/    the two Claude agents
    whatsapp/  incoming message routing, Meta webhook format, fixed messages
    services/  business rules (no AI): feasibility, orders, inventory, accounts, email, WhatsApp sending
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from .api import accounts, admin, contact, dashboard, demo, internal, public, webhooks
from .core import config
from .core.db import engine, init_db
from .seed import seed
from .services import orders
from .services.accounts import relink_accounts

log = logging.getLogger("karigarsetu")


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
        relink_accounts(s)   # supplier logins point at the maker with their WhatsApp number
    if not config.ADMIN_PASSWORD:
        log.warning("ADMIN_PASSWORD is not set: /admin is off and /docs is open. Set it before going online.")
    env_file = config.ENV_FILE
    log.info("Settings file: %s (%s)", env_file, "found" if env_file.exists() else "NOT FOUND")
    if config.SMTP_USERNAME and config.SMTP_PASSWORD:
        log.info("Email: on, via %s:%s as %s, contact form goes to %s",
                 config.SMTP_HOST, config.SMTP_PORT, config.SMTP_USERNAME, config.CONTACT_TO)
    else:
        log.warning("Email: OFF (SMTP_USERNAME / SMTP_PASSWORD missing in %s). Contact form messages are "
                    "saved but not emailed.", env_file)
    log.info("WhatsApp: %s", config.whatsapp_provider())
    yield


app = FastAPI(title="KarigarSetu API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.middleware("http")(admin.protect_docs)   # /docs, /redoc, /openapi.json: admin only (when ADMIN_PASSWORD is set)

for module in (public, contact, accounts, admin, dashboard, demo, internal, webhooks):
    app.include_router(module.router)


@app.exception_handler(orders.OrderError)
async def order_error(_, exc: orders.OrderError):
    """A business rule said no (e.g. not enough stock, wrong status): 409 with the reason."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# ---------- website (served from the same server, so the dashboard can call the API) ----------

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"   # karigarsetu/frontend


@app.get("/", include_in_schema=False)
def website():
    return FileResponse(FRONTEND / "index.html")


app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")
