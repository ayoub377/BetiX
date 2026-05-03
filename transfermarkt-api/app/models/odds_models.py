from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Float, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from app.models.team import Base


class TrackedMatch(Base):
    __tablename__ = "tracked_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String(50), unique=True, index=True, nullable=False)
    sport = Column(String(50), default="football")
    home_team = Column(String(255))
    away_team = Column(String(255))
    start_time = Column(String(100))
    start_time_raw = Column(String(100))
    status = Column(String(50), default="tracking")
    tracked_since = Column(String(100))
    # Odds API event mapping (populated when ODDS_API_KEY is set)
    odds_api_event_id = Column(String(100), nullable=True)
    odds_api_sport_key = Column(String(100), nullable=True)
    # Owning user (PR2). Nullable to keep legacy rows valid; new rows always
    # have it. We index it because /odds/track checks the user's concurrent
    # tracker count on every request.
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    # Per-tier polling cadence baked onto the row at /track time so the
    # startup recovery path in main.py can re-schedule jobs at the right
    # cadence after a restart, even if we change the tier matrix later.
    poll_interval_seconds = Column(Integer, nullable=True)


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String(50), nullable=False, index=True)
    sport = Column(String(50), default="football")
    timestamp = Column(String(100), nullable=False)
    home = Column(Float, nullable=True)
    draw = Column(Float, nullable=True)
    away = Column(Float, nullable=True)
    # Tennis fields (nullable — only populated for tennis)
    player1 = Column(Float, nullable=True)
    player2 = Column(Float, nullable=True)
    bookmaker = Column(String(255))
    # JSON-encoded sharp bookmaker odds (nullable for backward compat)
    sharp_odds = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_odds_snapshots_match_id_id", "match_id", "id"),
    )


class MatchResult(Base):
    """Final result for a tracked match. One row per match_id.

    Created when the pre-match tracking job stops at kickoff (with
    completed=False); filled in by the result-polling job once the Odds API
    reports the match as completed. Joins to ``tracked_matches`` and
    ``odds_snapshots`` on match_id to give a structured per-match dataset.
    """
    __tablename__ = "match_results"

    match_id = Column(String(50), primary_key=True)
    sport = Column(String(50), default="football")
    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)
    # 1X2 outcome: "home" | "draw" | "away" (football); "p1" | "p2" (tennis).
    outcome = Column(String(10), nullable=True)
    completed = Column(Boolean, default=False, nullable=False)
    # "odds_api" once filled; "timeout" if polling gave up.
    result_source = Column(String(50), nullable=True)
    fetched_at = Column(String(100), nullable=True)
    last_poll_at = Column(String(100), nullable=True)
    poll_attempts = Column(Integer, default=0, nullable=False)
