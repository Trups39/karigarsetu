"""Test settings, applied before the app is imported.

SQLite by default. To run the same tests on PostgreSQL:
  TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/karigarsetu_test python -m pytest -q
"""
import os
import tempfile

os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DEMO_TODAY"] = "2026-11-16"
os.environ["INTERNAL_API_KEY"] = "test-key"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["SAMPLE_MAKERS"] = "true"        # tests use the sample suppliers from db/seed.sql
os.environ["SEED_DEMO_ORDERS"] = "false"   # tests start with no orders; one test turns them on
os.environ["DEMO_RETAILER_PHONE"] = ""
os.environ["ADMIN_EMAIL"] = "admin@karigarsetu.co.in"
os.environ["ADMIN_PASSWORD"] = "test-admin"
os.environ["COOKIE_SECURE"] = "false"
os.environ["BCRYPT_ROUNDS"] = "4"          # fast hashing in tests only
os.environ["SMTP_USERNAME"] = ""           # never send real email from tests
os.environ["SMTP_PASSWORD"] = ""
os.environ["BOT_WHATSAPP_NUMBER"] = ""
os.environ["PUBLIC_URL"] = "http://testserver"
