"""
Database engine, session factory, and FastAPI dependency.

Usage in a router:
    from shared.db.session import get_db
    @router.get("/...")
    def my_endpoint(db: Session = Depends(get_db)):
        ...
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Deferred import — config is loaded at app startup, not at module import
# time, so we read DATABASE_URL lazily via the get_db dependency or
# explicitly via init_engine().
_engine = None
_SessionLocal = None


def init_engine(database_url: str) -> None:
    """Initialise the module-level engine + session factory."""
    global _engine, _SessionLocal
    _engine = create_engine(database_url, pool_pre_ping=True)
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and closes it after."""
    if _SessionLocal is None:
        raise RuntimeError(
            "Database not initialised — call init_engine() at app startup."
        )
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
