"""Check that Python can connect to your PostgreSQL database. Changes nothing.

Run:  python db_check.py
Needs: pip install "psycopg[binary]" python-dotenv
       DATABASE_URL=postgresql://postgres:YOURPASSWORD@localhost:5432/karigarsetu in .env
"""
import os
import psycopg
from dotenv import load_dotenv

load_dotenv()
url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL is missing from .env")

try:
    with psycopg.connect(url) as conn:
        db, user, version = conn.execute(
            "SELECT current_database(), current_user, version()").fetchone()
        print("Connected!")
        print("  Database:", db)
        print("  User:    ", user)
        print("  Server:  ", version.split(",")[0])
except psycopg.OperationalError as e:
    print("Could not connect:")
    print(" ", str(e).strip().splitlines()[-1])
