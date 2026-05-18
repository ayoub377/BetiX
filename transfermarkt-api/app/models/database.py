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
    # Telegram alerts (premium feature). chat_id is set after the deep-link
    # flow completes; threshold_pct is the abs % move from opening odds at
    # which we DM the user.
    'ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_chat_id VARCHAR(64)',
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_alerts_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    'ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_alert_threshold_pct DOUBLE PRECISION',
    'CREATE INDEX IF NOT EXISTS ix_users_telegram_chat_id ON users (telegram_chat_id)',
    # Multi-market tracking. Each scrape now writes one snapshot per
    # configured market; legacy 1X2-only rows get 'market = 1x2' via the
    # NOT NULL DEFAULT clause, so the index below sees a consistent shape.
    "ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS market VARCHAR(20) NOT NULL DEFAULT '1x2'",
    'ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS over DOUBLE PRECISION',
    'ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS under DOUBLE PRECISION',
    'ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS line DOUBLE PRECISION',
    'CREATE INDEX IF NOT EXISTS ix_odds_snapshots_match_market_id ON odds_snapshots (match_id, market, id)',
    # JSON list of markets per tracked match. NULL means "legacy 1X2-only",
    # so we don't need to backfill before deploying.
    'ALTER TABLE tracked_matches ADD COLUMN IF NOT EXISTS markets TEXT',
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
