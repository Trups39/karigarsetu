"""Settings, read from environment variables (see .env.example)."""
import os
from datetime import date
from pathlib import Path


def _load_env_file() -> None:
    """Read backend/.env if it exists. Real environment variables win."""
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./karigarsetu.db")

# Shared secret for internal calls (the AI agent and the WhatsApp webhook use it).
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "dev-internal-key")

# ---------- Supplier login (email + password) and admin approval ----------
# Admin password for /admin (approve new suppliers). When it's set, /docs is also admin-only.
# Leave empty only on your own laptop.
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()   # admin logs in with this email + ADMIN_PASSWORD
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@karigarsetu.in")
SUPPLIER_SESSION_DAYS = int(os.getenv("SUPPLIER_SESSION_DAYS", "14"))   # stay logged in this long
ADMIN_SESSION_HOURS = int(os.getenv("ADMIN_SESSION_HOURS", "12"))
MAX_FAILED_LOGINS = int(os.getenv("MAX_FAILED_LOGINS", "5"))             # then the account is locked...
LOGIN_LOCK_MINUTES = int(os.getenv("LOGIN_LOCK_MINUTES", "15"))          # ...for this long
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")   # true on the VPS (HTTPS)
BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", "12"))

# Claude, for the Sales Agent. Without a key the agent replies with a fallback message.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))   # room for Claude's thinking plus the reply

# Which WhatsApp service sends messages: "meta", "twilio", or "none" (messages are only stored).
# Leave empty to choose automatically: Meta if its settings are filled in, else Twilio, else none.
WHATSAPP_PROVIDER = os.getenv("WHATSAPP_PROVIDER", "").lower()

# WhatsApp via Meta Cloud API (developers.facebook.com → your app → WhatsApp → API Setup)
META_WHATSAPP_TOKEN = os.getenv("META_WHATSAPP_TOKEN", "")      # "Generate access token" (starts with EAA)
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID", "")    # "Phone number ID", not the phone number
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")          # any secret word; type the same in Meta's webhook form
META_APP_SECRET = os.getenv("META_APP_SECRET", "")              # App settings → Basic → App secret
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v25.0")

# WhatsApp via Twilio. Without these, outgoing messages are only stored in the outbox table.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")  # e.g. "whatsapp:+14155238886"

# Sample suppliers (db/seed.sql: Kolhapur Chappal Kendra, Patil Chappal Udyog with designs, stock and past orders).
# They show as approved suppliers on /admin but have no website login. Your own maker is never preset:
# sign up on the website and approve it at /admin.
SAMPLE_MAKERS = os.getenv("SAMPLE_MAKERS", "true").lower() in ("1", "true", "yes")

# Load db/demo_orders.sql (past orders and history) when seeding an empty database.
SEED_DEMO_ORDERS = os.getenv("SEED_DEMO_ORDERS", "true").lower() in ("1", "true", "yes")

# Your real retailer test phone, applied after every seed/reset (digits with country code, no +):
# DEMO_RETAILER_PHONE becomes Pune Footwear House. (Your maker phone is not preset: sign up with it.)
DEMO_RETAILER_PHONE = os.getenv("DEMO_RETAILER_PHONE", "").strip().lstrip("+")

# Demo buttons on the dashboard ("Simulate new WhatsApp order", "Simulate retailer accepts").
# Turn off in production.
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() in ("1", "true", "yes")

# Fix "today" for a repeatable demo (YYYY-MM-DD). Empty = real date.
DEMO_TODAY = os.getenv("DEMO_TODAY", "")


def today() -> date:
    return date.fromisoformat(DEMO_TODAY) if DEMO_TODAY else date.today()


def whatsapp_provider() -> str:
    if WHATSAPP_PROVIDER in ("meta", "twilio", "none"):
        return WHATSAPP_PROVIDER
    if META_WHATSAPP_TOKEN and META_PHONE_NUMBER_ID:
        return "meta"
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM:
        return "twilio"
    return "none"
