"""Write the CREATE TABLE statements for the current models to backend/db/schema.<dialect>.sql.

    python -m app.schema_dump

The app creates tables by itself (python -m app.seed --reset), so these files are for reading,
documentation, or creating tables by hand. Regenerate them after changing app/models.py.
"""
from pathlib import Path

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import SQLModel

from .core import models  # noqa: F401  (registers tables)

DB_DIR = Path(__file__).resolve().parents[1] / "db"


def dump(dialect, name: str) -> Path:
    lines = [f"-- KarigarSetu tables ({name}). Generated from app/models.py by: python -m app.schema_dump",
             "-- The app creates these automatically; this file is for reference or manual setup.", ""]
    if name == "postgres":   # PostgreSQL stores the order status as its own ENUM type
        from sqlalchemy import Enum
        done = set()
        for table in SQLModel.metadata.sorted_tables:
            for col in table.columns:
                if isinstance(col.type, Enum) and col.type.name not in done:
                    done.add(col.type.name)
                    values = ", ".join(f"'{v}'" for v in col.type.enums)
                    lines += [f"CREATE TYPE {col.type.name} AS ENUM ({values});", ""]
    for table in SQLModel.metadata.sorted_tables:   # parents before children (foreign keys)
        lines.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            lines.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
        lines.append("")
    path = DB_DIR / f"schema.{name}.sql"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


if __name__ == "__main__":
    for d, n in [(sqlite.dialect(), "sqlite"), (postgresql.dialect(), "postgres")]:
        print("Wrote", dump(d, n))
