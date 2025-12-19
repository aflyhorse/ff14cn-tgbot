from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import load_settings

settings = load_settings()
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    # Lazy import to avoid circular dependencies during metadata creation
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # Lightweight SQLite migration for additive columns.
    # Keeps existing installations working without manual ALTER TABLE.
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(events)").fetchall()
        cols = {r[1] for r in rows}  # (cid, name, type, notnull, dflt_value, pk)

        if "is_active" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE events ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"
            )
        if "last_seen_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE events ADD COLUMN last_seen_at DATETIME")
        if "removed_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE events ADD COLUMN removed_at DATETIME")


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
