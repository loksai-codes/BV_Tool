"""Minimal, ordered schema migration runner.

Each migration is (version, description, callable(connection)). Applied versions
are recorded in ``schema_version``. Add new migrations to MIGRATIONS with an
increasing version; never edit an applied one. For PostgreSQL deployments this
can be replaced by Alembic without changing the ORM models.

Usage:  python -m database.migrations.migrate
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy import Connection, Engine, inspect, select

from database.models import Base, SchemaVersion


def _v1_initial(conn: Connection) -> None:
    Base.metadata.create_all(conn)


MIGRATIONS: list[tuple[int, str, Callable[[Connection], None]]] = [
    (1, "initial schema", _v1_initial),
]


def current_version(engine: Engine) -> int:
    if not inspect(engine).has_table("schema_version"):
        return 0
    with engine.connect() as conn:
        versions = conn.execute(select(SchemaVersion.version)).scalars().all()
    return max(versions, default=0)


def upgrade(engine: Engine) -> int:
    SchemaVersion.__table__.create(engine, checkfirst=True)
    applied = current_version(engine)
    for version, description, fn in MIGRATIONS:
        if version <= applied:
            continue
        with engine.begin() as conn:
            fn(conn)
            conn.execute(SchemaVersion.__table__.insert().values(version=version, description=description))
        applied = version
    return applied


if __name__ == "__main__":  # pragma: no cover
    from database.repository import make_engine
    from config.settings import get_settings

    s = get_settings()
    s.ensure_dirs()
    print("Schema version:", upgrade(make_engine(s.database_url)))
