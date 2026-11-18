"""Load starting data from backend/db/*.sql.

    python -m app.seed            load into an empty database (does nothing if it already has data)
    python -m app.seed --reset    delete everything (except supplier logins), recreate tables, load again

retailers.sql    sample shops that order on WhatsApp
seed.sql         sample suppliers: makers, their designs, stock and supplier accounts (SAMPLE_MAKERS=true, default)
demo_orders.sql  past orders for the sample suppliers (SEED_DEMO_ORDERS=true, default)

Your own maker is never preset: sign up on the website, approve it at /admin, then log in.
"""
import re
import sys
from pathlib import Path

from sqlmodel import Session, SQLModel, select

from .core import config
from .core.db import engine, init_db
from .core.models import Maker, Retailer

DB_DIR = Path(__file__).resolve().parents[1] / "db"


def run_sql_file(session: Session, path: Path) -> int:
    """Run every statement in a .sql file. Full-line '--' comments are ignored."""
    text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.strip().startswith("--"))
    statements = [s.strip() for s in re.split(r";\s*(?:\n|$)", text) if s.strip()]
    conn = session.connection()
    if conn.dialect.name == "postgresql":
        conn.exec_driver_sql("SET TIME ZONE 'UTC'")   # times in the .sql files are UTC
    for stmt in statements:
        conn.exec_driver_sql(stmt)
    return len(statements)


def seed(session: Session) -> bool:
    """Load the SQL files into an empty database. Returns True if it loaded anything."""
    if session.exec(select(Retailer)).first() or session.exec(select(Maker)).first():
        return False
    run_sql_file(session, DB_DIR / "retailers.sql")
    if config.SAMPLE_MAKERS:
        run_sql_file(session, DB_DIR / "seed.sql")
        if config.SEED_DEMO_ORDERS:
            run_sql_file(session, DB_DIR / "demo_orders.sql")
    use_my_phones(session)
    session.commit()
    from .services.accounts import relink_accounts
    relink_accounts(session)   # supplier logins kept by --reset point at their maker again
    return True


def use_my_phones(session: Session) -> None:
    """Swap the sample shop's number for your real retailer test phone (DEMO_RETAILER_PHONE in .env)."""
    from .core.models import Order, Retailer
    if config.DEMO_RETAILER_PHONE:
        r = session.exec(select(Retailer).where(Retailer.name == "Pune Footwear House")).first()
        if r:
            for o in session.exec(select(Order).where(Order.retailer_id == r.id)):
                o.retailer_phone = config.DEMO_RETAILER_PHONE
                session.add(o)
            r.phone = config.DEMO_RETAILER_PHONE
            session.add(r)


SAMPLE_NO_LOGIN = "sample-no-login"   # password_hash of the sample suppliers in seed.sql: they can't log in


def reset() -> int:
    """Wipe and recreate all tables, but keep supplier logins (email, password, approval).
    Returns how many were kept. They are linked to their maker again when the data is loaded."""
    from sqlalchemy.exc import SQLAlchemyError

    from .core.models import SupplierAccount
    try:
        with Session(engine) as s:
            saved = [a.model_dump(exclude={"id", "maker_id"}) for a in s.exec(select(SupplierAccount))
                     if a.password_hash != SAMPLE_NO_LOGIN]   # sample suppliers come back from seed.sql
    except SQLAlchemyError:   # an old database without the table
        saved = []
    SQLModel.metadata.drop_all(engine)
    init_db()
    with Session(engine) as s:
        for row in saved:
            s.add(SupplierAccount(**row))
        s.commit()
    return len(saved)


if __name__ == "__main__":
    if "--reset" in sys.argv:
        kept = reset()
        print(f"Database wiped and tables recreated (kept {kept} supplier login(s)).")
    else:
        init_db()
    with Session(engine) as s:
        loaded = seed(s)
    if not loaded:
        print("Database already has data. Use --reset to start again.")
    else:
        print("Loaded sample retailers" + (", sample suppliers (Kolhapur Chappal Kendra, Patil Chappal Udyog)"
                                           if config.SAMPLE_MAKERS else "")
              + (" and their past orders" if config.SAMPLE_MAKERS and config.SEED_DEMO_ORDERS else "") + ".")
        print("Your maker: sign up on the website, approve it at /admin, then log in.")
    if loaded and config.DEMO_RETAILER_PHONE:
        print(f"Your retailer phone: Pune Footwear House = {config.DEMO_RETAILER_PHONE}")
