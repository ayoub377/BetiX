import os
import logging

from sqlalchemy import create_engine, text
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


# Idempotent additive schema changes for tables already created by
# Base.metadata.create_all() in earlier deploys. Real Alembic migrations are
# planned for a later PR — until then this keeps prod migration-free.
_SOFT_MIGRATIONS = (
    # PR2: tier-aware tracking — owner FK + per-row polling cadence.
    'ALTER TABLE tracked_matches ADD COLUMN IF NOT EXISTS user_id UUID',
    'ALTER TABLE tracked_matches ADD COLUMN IF NOT EXISTS poll_interval_seconds INTEGER',
    'CREATE INDEX IF NOT EXISTS ix_tracked_matches_user_id ON tracked_matches (user_id)',
)


def _apply_soft_migrations() -> None:
    with engine.begin() as conn:
        for stmt in _SOFT_MIGRATIONS:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                # Don't crash boot on a single bad statement — log and continue
                # so a deploy never wedges on a benign migration race.
                logger.warning("Soft migration failed (%s): %s", stmt, e)


def init_db():
    """Create all tables that don't exist yet. Safe to call multiple times."""
    from app.models.team import Base  # noqa: F811 — Base registers all models
    import app.models.odds_models  # noqa: F401 — register OddsSnapshot/TrackedMatch
    import app.models.users  # noqa: F401 — register User

    Base.metadata.create_all(bind=engine)
    _apply_soft_migrations()
    logger.info("Database tables ensured (url=%s).", DATABASE_URL.split("@")[-1])
