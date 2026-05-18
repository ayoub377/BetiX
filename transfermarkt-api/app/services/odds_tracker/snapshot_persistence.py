"""
Persistence layer for odds snapshots and match metadata.
Writes to PostgreSQL (or any SQLAlchemy-supported DB) for long-term storage.
"""
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.markets import DEFAULT_MARKETS, MARKET_1X2, is_supported
from app.models.odds_models import TrackedMatch, OddsSnapshot, MatchResult

logger = logging.getLogger(__name__)


def persist_match(session: Session, match_id: str, meta: dict):
    """Insert or ignore match metadata. Idempotent — skips if already exists.

    Reads ``user_id`` and ``poll_interval_seconds`` from ``meta`` when present
    (set by the /odds/track endpoint based on the authenticated user's tier).
    """
    existing = session.query(TrackedMatch).filter_by(match_id=match_id).first()
    if existing:
        return
    # markets is stored as JSON text so we can extend the shape later
    # (e.g. per-market thresholds) without a column rename. None is fine
    # for legacy callers and is interpreted as DEFAULT_MARKETS downstream.
    markets_raw = meta.get("markets")
    markets_json = json.dumps(markets_raw) if markets_raw else None

    row = TrackedMatch(
        match_id=match_id,
        sport=meta.get("sport", "football"),
        home_team=meta.get("home_team"),
        away_team=meta.get("away_team"),
        start_time=meta.get("start_time"),
        start_time_raw=meta.get("start_time_raw"),
        status=meta.get("status", "tracking"),
        tracked_since=meta.get("tracked_since"),
        odds_api_event_id=meta.get("odds_api_event_id"),
        odds_api_sport_key=meta.get("odds_api_sport_key"),
        user_id=meta.get("user_id"),
        poll_interval_seconds=meta.get("poll_interval_seconds"),
        markets=markets_json,
    )
    session.add(row)
    session.commit()
    logger.info("Persisted match %s to database.", match_id)


def persist_snapshot(session: Session, match_id: str, snapshot: dict):
    """Append a single odds snapshot row.

    The snapshot dict carries a ``market`` key (added by the scheduler).
    Outcome fields are populated based on the market — 1X2 fills
    home/draw/away, OU_2.5 fills over/under/line, and the unused fields
    stay NULL so analytical queries can filter by ``market`` without
    worrying about cross-contamination.
    """
    sharp_odds_raw = snapshot.get("sharp_odds")
    sharp_odds_json = json.dumps(sharp_odds_raw) if sharp_odds_raw else None
    market = snapshot.get("market") or MARKET_1X2

    row = OddsSnapshot(
        match_id=match_id,
        sport=snapshot.get("sport", "football"),
        timestamp=snapshot.get("timestamp"),
        market=market,
        home=snapshot.get("home"),
        draw=snapshot.get("draw"),
        away=snapshot.get("away"),
        player1=snapshot.get("player1"),
        player2=snapshot.get("player2"),
        over=snapshot.get("over"),
        under=snapshot.get("under"),
        line=snapshot.get("line"),
        bookmaker=snapshot.get("bookmaker"),
        sharp_odds=sharp_odds_json,
    )
    session.add(row)
    session.commit()
    logger.debug("Persisted snapshot for match %s (market=%s).", match_id, market)


def update_match_status(session: Session, match_id: str, status: str):
    """Update the status field of a tracked match."""
    row = session.query(TrackedMatch).filter_by(match_id=match_id).first()
    if row:
        row.status = status
        session.commit()
        logger.info("Updated match %s status to '%s'.", match_id, status)


def update_match_start_time(
    session: Session,
    match_id: str,
    start_time: Optional[str],
    start_time_raw: Optional[str],
):
    """Update the start_time / start_time_raw fields of a tracked match.

    ``start_time_raw`` is preserved when None is passed — Odds API refreshes
    don't have a "raw" representation, but we still want to keep whichever
    raw FlashScore string was last captured for debugging.
    """
    row = session.query(TrackedMatch).filter_by(match_id=match_id).first()
    if row:
        row.start_time = start_time
        if start_time_raw is not None:
            row.start_time_raw = start_time_raw
        session.commit()
        logger.info("Updated match %s start_time to '%s'.", match_id, start_time)


def get_match_snapshots(
    session: Session,
    match_id: str,
    market: Optional[str] = None,
) -> list[dict]:
    """Return snapshots for a match, ordered by insertion order.

    ``market`` filters to a specific market id (e.g. ``"ou_2.5"``). When
    omitted, returns every market interleaved — useful for backward
    compatibility with callers that don't yet care about markets.
    """
    query = session.query(OddsSnapshot).filter_by(match_id=match_id)
    if market is not None:
        query = query.filter(OddsSnapshot.market == market)
    rows = query.order_by(OddsSnapshot.id).all()

    result = []
    for r in rows:
        # Snapshot ``market`` may be NULL on rows persisted before the
        # column existed — treat as 1X2 so the API surface stays clean.
        snap_market = (r.market or MARKET_1X2)
        snap = {
            "timestamp": r.timestamp,
            "sport": r.sport or "football",
            "market": snap_market,
            "bookmaker": r.bookmaker,
            "sharp_odds": json.loads(r.sharp_odds) if r.sharp_odds else None,
        }
        if r.sport == "tennis":
            snap["player1"] = r.player1
            snap["player2"] = r.player2
        elif snap_market == MARKET_1X2:
            snap["home"] = r.home
            snap["draw"] = r.draw
            snap["away"] = r.away
        else:
            # Over/Under (and future BTTS) markets.
            snap["over"] = r.over
            snap["under"] = r.under
            snap["line"] = r.line
        result.append(snap)
    return result


def get_all_matches_from_db(session: Session, user_id: Optional[str] = None) -> list[dict]:
    """Return all matches ever tracked, most recent first.

    When ``user_id`` is provided, only matches owned by that user are returned.
    Legacy rows without a ``user_id`` are excluded under this filter so a fresh
    user never sees another account's pre-existing trackers.
    """
    query = session.query(TrackedMatch)
    if user_id is not None:
        query = query.filter(TrackedMatch.user_id == user_id)
    rows = query.order_by(TrackedMatch.id.desc()).all()

    def _markets(raw: Optional[str]) -> list[str]:
        if not raw:
            return list(DEFAULT_MARKETS)
        try:
            parsed = json.loads(raw)
            filtered = [m for m in parsed if isinstance(m, str) and is_supported(m)]
            return filtered or list(DEFAULT_MARKETS)
        except (json.JSONDecodeError, TypeError):
            return list(DEFAULT_MARKETS)

    return [
        {
            "match_id": r.match_id,
            "sport": r.sport or "football",
            "home_team": r.home_team,
            "away_team": r.away_team,
            "start_time": r.start_time,
            "start_time_raw": r.start_time_raw,
            "status": r.status,
            "tracked_since": r.tracked_since,
            "odds_api_event_id": r.odds_api_event_id,
            "odds_api_sport_key": r.odds_api_sport_key,
            "user_id": str(r.user_id) if r.user_id else None,
            "markets": _markets(r.markets),
        }
        for r in rows
    ]


def _outcome_for_scores(
    sport: str,
    home_score: Optional[int],
    away_score: Optional[int],
) -> Optional[str]:
    """Derive 1X2 outcome label from scores. None when scores are missing."""
    if home_score is None or away_score is None:
        return None
    if sport == "tennis":
        return "p1" if home_score > away_score else "p2"
    if home_score > away_score:
        return "home"
    if home_score < away_score:
        return "away"
    return "draw"


def upsert_match_result(
    session: Session,
    match_id: str,
    sport: str,
    completed: bool = False,
) -> MatchResult:
    """Insert a pending result row if one doesn't already exist; return it.

    Idempotent — safe to call from both the kickoff hook and the polling
    job's first iteration.
    """
    row = session.query(MatchResult).filter_by(match_id=match_id).first()
    if row:
        return row
    row = MatchResult(
        match_id=match_id,
        sport=sport or "football",
        completed=completed,
        poll_attempts=0,
    )
    session.add(row)
    session.commit()
    logger.info("Created pending match_result row for %s.", match_id)
    return row


def mark_result_completed(
    session: Session,
    match_id: str,
    sport: str,
    home_score: Optional[int],
    away_score: Optional[int],
    fetched_at: str,
    result_source: str = "odds_api",
) -> None:
    """Write final scores + outcome to the match_results row."""
    row = session.query(MatchResult).filter_by(match_id=match_id).first()
    if not row:
        row = MatchResult(match_id=match_id, sport=sport or "football")
        session.add(row)

    row.sport = sport or row.sport or "football"
    row.home_score = home_score
    row.away_score = away_score
    row.outcome = _outcome_for_scores(row.sport, home_score, away_score)
    row.completed = True
    row.result_source = result_source
    row.fetched_at = fetched_at
    row.last_poll_at = fetched_at
    session.commit()
    logger.info(
        "Recorded final result for %s: %s-%s outcome=%s",
        match_id, home_score, away_score, row.outcome,
    )


def record_poll_attempt(
    session: Session,
    match_id: str,
    last_poll_at: str,
) -> int:
    """Increment poll_attempts on the row, return the new count."""
    row = session.query(MatchResult).filter_by(match_id=match_id).first()
    if not row:
        return 0
    row.last_poll_at = last_poll_at
    row.poll_attempts = (row.poll_attempts or 0) + 1
    session.commit()
    return row.poll_attempts


def mark_result_timeout(session: Session, match_id: str, fetched_at: str) -> None:
    """Mark a result row as timed-out after exceeding poll budget."""
    row = session.query(MatchResult).filter_by(match_id=match_id).first()
    if not row:
        return
    row.result_source = "timeout"
    row.last_poll_at = fetched_at
    session.commit()
    logger.info("Marked match_result %s as timeout after %d polls.", match_id, row.poll_attempts)


def get_match_result_from_db(session: Session, match_id: str) -> Optional[dict]:
    """Return the match_results row as a dict, or None if not present."""
    row = session.query(MatchResult).filter_by(match_id=match_id).first()
    if not row:
        return None
    return {
        "match_id": row.match_id,
        "sport": row.sport,
        "home_score": row.home_score,
        "away_score": row.away_score,
        "outcome": row.outcome,
        "completed": bool(row.completed),
        "result_source": row.result_source,
        "fetched_at": row.fetched_at,
        "last_poll_at": row.last_poll_at,
        "poll_attempts": row.poll_attempts or 0,
    }


def get_pending_result_match_ids(session: Session) -> list[str]:
    """Return match_ids of result rows where completed=False — for startup recovery."""
    rows = (
        session.query(MatchResult.match_id)
        .filter(MatchResult.completed.is_(False))
        .all()
    )
    return [r[0] for r in rows]


def get_match_meta_from_db(session: Session, match_id: str) -> Optional[dict]:
    """Return match metadata as a dict, or None if not found.

    ``markets`` is normalised to a list of supported market ids — NULL rows
    are returned as the legacy default (1X2-only), unknown ids are dropped.
    The list is guaranteed non-empty (we coerce to default if filtering left
    nothing) so callers can iterate without checking.
    """
    row = session.query(TrackedMatch).filter_by(match_id=match_id).first()
    if not row:
        return None

    if row.markets:
        try:
            raw = json.loads(row.markets)
            markets = [m for m in raw if isinstance(m, str) and is_supported(m)]
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Could not parse markets JSON for match %s: %r", match_id, row.markets,
            )
            markets = []
        if not markets:
            markets = list(DEFAULT_MARKETS)
    else:
        markets = list(DEFAULT_MARKETS)

    return {
        "match_id": row.match_id,
        "sport": row.sport or "football",
        "home_team": row.home_team,
        "away_team": row.away_team,
        "start_time": row.start_time,
        "start_time_raw": row.start_time_raw,
        "status": row.status,
        "tracked_since": row.tracked_since,
        "odds_api_event_id": row.odds_api_event_id,
        "odds_api_sport_key": row.odds_api_sport_key,
        "user_id": str(row.user_id) if row.user_id else None,
        "poll_interval_seconds": row.poll_interval_seconds,
        "markets": markets,
    }
