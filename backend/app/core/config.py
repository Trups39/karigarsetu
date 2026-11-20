"""Settings, read from environment variables (see .env.example)."""

import os
from datetime import date
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"  # backend/.env


def _load_env_file() -> None:
    """Read backend/.env if it exists. Real environment variables win."""
    env = ENV_FILE
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def _env(name: str, default: str = "") -> str:
    """A setting from the environment / backend/.env. Missing or empty = use the default."""
    value = os.getenv(name)
    return default if value is None or not value.strip() else value.strip()


DATABASE_URL = _env("DATABASE_URL", "sqlite:///./karigarsetu.db")

# Shared secret for internal calls (the AI agent and the WhatsApp webhook use it).
INTERNAL_API_KEY = _env("INTERNAL_API_KEY", "dev-internal-key")

# ---------- Supplier login (email + password) and admin approval ----------
# Admin password for /admin (approve new suppliers). When it's set, /docs is also admin-only.
# Leave empty only on your own laptop.
ADMIN_EMAIL = _env("ADMIN_EMAIL", "").strip().lower()  # admin logs in with this email + ADMIN_PASSWORD
ADMIN_PASSWORD = _env("ADMIN_PASSWORD", "")
SUPPORT_EMAIL = _env("SUPPORT_EMAIL", "contact@karigarsetu.co.in")

# ---------- Email on our GoDaddy domain (GoDaddy Professional Email): contact form + supplier emails ----------
SMTP_HOST = _env("SMTP_HOST", "smtpout.secureserver.net")
SMTP_PORT = int(_env("SMTP_PORT", "465"))  # 465 = SSL, 587 = STARTTLS
SMTP_USERNAME = _env("SMTP_USERNAME", "")  # the mailbox, e.g. contact@karigarsetu.co.in
SMTP_PASSWORD = _env("SMTP_PASSWORD", "")  # only in backend/.env, never in the repo
CONTACT_TO = _env("CONTACT_TO", "contact@karigarsetu.co.in")  # where contact-form messages go
PUBLIC_URL = _env("PUBLIC_URL", "http://localhost:8000").rstrip("/")  # e.g. https://karigarsetu.co.in

# The KarigarSetu WhatsApp bot (Meta number), digits only. "Order on WhatsApp" buttons open a chat with it.
BOT_WHATSAPP_NUMBER = _env("BOT_WHATSAPP_NUMBER", "").strip().lstrip("+").replace(" ", "").replace("-", "")
SUPPLIER_SESSION_DAYS = int(_env("SUPPLIER_SESSION_DAYS", "14"))  # stay logged in this long
ADMIN_SESSION_HOURS = int(_env("ADMIN_SESSION_HOURS", "12"))
MAX_FAILED_LOGINS = int(_env("MAX_FAILED_LOGINS", "5"))  # then the account is locked...
LOGIN_LOCK_MINUTES = int(_env("LOGIN_LOCK_MINUTES", "15"))  # ...for this long
COOKIE_SECURE = _env("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")  # true on the VPS (HTTPS)
BCRYPT_ROUNDS = int(_env("BCRYPT_ROUNDS", "12"))

# Claude, for the Sales Agent. Without a key the agent replies with a fallback message.
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = _env("CLAUDE_MODEL", "claude-sonnet-5-5")
CLAUDE_MAX_TOKENS = int(_env("CLAUDE_MAX_TOKENS", "4096"))  # room for Claude's thinking plus the reply

# Which WhatsApp service sends messages: "meta" or "none" (messages are only stored).
# Leave empty to choose automatically: Meta if its settings are filled in, else none.
WHATSAPP_PROVIDER = _env("WHATSAPP_PROVIDER", "").lower()

# WhatsApp via Meta Cloud API (developers.facebook.com → your app → WhatsApp → API Setup)
META_WHATSAPP_TOKEN = _env("META_WHATSAPP_TOKEN", "")  # "Generate access token" (starts with EAA)
META_PHONE_NUMBER_ID = _env("META_PHONE_NUMBER_ID", "")  # "Phone number ID", not the phone number
META_VERIFY_TOKEN = _env("META_VERIFY_TOKEN", "")  # any secret word; type the same in Meta's webhook form
META_APP_SECRET = _env("META_APP_SECRET", "")  # App settings → Basic → App secret
META_GRAPH_VERSION = _env("META_GRAPH_VERSION", "v25.0")


# Sample suppliers (db/seed.sql: Kolhapur Chappal Kendra, Patil Chappal Udyog with designs, stock and past orders).
# They show as approved suppliers on /admin but have no website login. Your own maker is never preset:
# sign up on the website and approve it at /admin.
SAMPLE_MAKERS = _env("SAMPLE_MAKERS", "true").lower() in ("1", "true", "yes")

# Load db/demo_orders.sql (past orders and history) when seeding an empty database.
SEED_DEMO_ORDERS = _env("SEED_DEMO_ORDERS", "true").lower() in ("1", "true", "yes")

# Your real retailer test phone, applied after every seed/reset (digits with country code, no +):
# DEMO_RETAILER_PHONE becomes Pune Footwear House. (Your maker phone is not preset: sign up with it.)
DEMO_RETAILER_PHONE = _env("DEMO_RETAILER_PHONE", "").strip().lstrip("+")

# Demo buttons on the dashboard ("Simulate new WhatsApp order", "Simulate retailer accepts").
# Turn off in production.
DEMO_MODE = _env("DEMO_MODE", "true").lower() in ("1", "true", "yes")

# Fix "today" for a repeatable demo (YYYY-MM-DD). Empty = real date.
DEMO_TODAY = _env("DEMO_TODAY", "")


def today() -> date:
    return date.fromisoformat(DEMO_TODAY) if DEMO_TODAY else date.today()


def whatsapp_provider() -> str:
    if WHATSAPP_PROVIDER in ("meta", "none"):
        return WHATSAPP_PROVIDER
    if META_WHATSAPP_TOKEN and META_PHONE_NUMBER_ID:
        return "meta"
    return "none"
