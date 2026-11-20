from sqlmodel import Session, SQLModel, create_engine

from . import config

if config.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
elif "+psycopg" in config.DATABASE_URL:
    # No server-side prepared statements: they break when tables are recreated
    # (python -m app.seed --reset) while the server is still running.
    connect_args = {"prepare_threshold": None}
else:
    connect_args = {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)


def init_db() -> None:
    from sqlalchemy.exc import OperationalError

    from . import models  # noqa: F401  (registers tables)

    try:
        SQLModel.metadata.create_all(engine)
        _add_missing_columns()
    except OperationalError as e:
        raise SystemExit(
            f"\nCan't connect to the database at {engine.url.render_as_string(hide_password=True)}\n"
            "Check that PostgreSQL is running, the database exists, and the user and password in "
            "DATABASE_URL (backend/.env) are right.\n"
            f"Details: {e.orig}\n"
        ) from None


def _add_missing_columns() -> None:
    """create_all() makes new tables but never changes old ones. Add any new nullable model column
    to an existing table, so a deploy doesn't need a hand-written ALTER TABLE."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have and col.nullable:
                    kind = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {kind}'))


def get_session():
    with Session(engine) as session:
        yield session
