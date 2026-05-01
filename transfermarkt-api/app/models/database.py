import os
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/betting_analysis",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Yield a session, auto-close on exit. Use as a FastAPI dependency or context manager."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables that don't exist yet. Safe to call multiple times."""
    from app.models.team import Base  # noqa: F811 — Base registers all models
    import app.models.odds_models  # noqa: F401 — register OddsSnapshot/TrackedMatch
    import app.models.users  # noqa: F401 — register User

    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ensured (url=%s).", DATABASE_URL.split("@")[-1])
