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

        # One-time data migration: historically, scraped activity times were stored
        # as naive China time (UTC+8). The app logic now stores start_at/end_at as
        # naive UTC for consistent comparisons on UTC servers.
        # We track completion via PRAGMA user_version to avoid double conversion.
        try:
            user_version = conn.exec_driver_sql("PRAGMA user_version").scalar() or 0
        except Exception:
            user_version = 0

        if int(user_version) < 1:
            # Convert only the activity time fields.
            # NOTE: SQLite datetime() drops microseconds; acceptable for this app.
            conn.exec_driver_sql(
                "UPDATE events SET start_at = datetime(start_at, '-8 hours') WHERE start_at IS NOT NULL"
            )
            conn.exec_driver_sql(
                "UPDATE events SET end_at = datetime(end_at, '-8 hours') WHERE end_at IS NOT NULL"
            )
            conn.exec_driver_sql("PRAGMA user_version = 1")


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
