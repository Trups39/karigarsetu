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
    except OperationalError as e:
        raise SystemExit(
            f"\nCan't connect to the database at {engine.url.render_as_string(hide_password=True)}\n"
            "Check that PostgreSQL is running, the database exists, and the user and password in "
            "DATABASE_URL (backend/.env) are right.\n"
            f"Details: {e.orig}\n"
        ) from None


def get_session():
    with Session(engine) as session:
        yield session
