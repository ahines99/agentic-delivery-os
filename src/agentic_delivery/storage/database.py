"""SQLAlchemy engine setup. SQLite is a development/test convenience, not PostgreSQL proof."""

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import StaticPool


def create_database(url: str) -> Engine:
    if url.startswith("sqlite"):
        if url.endswith(":memory:"):
            engine = create_engine(
                url, poolclass=StaticPool, connect_args={"check_same_thread": False}
            )
        else:
            if url.startswith("sqlite+pysqlite:///"):
                Path(url.removeprefix("sqlite+pysqlite:///")).parent.mkdir(
                    parents=True, exist_ok=True
                )
            engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection: object, _: object) -> None:
            import sqlite3

            if isinstance(connection, sqlite3.Connection):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")
    else:
        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    return engine
