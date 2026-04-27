"""
Post-match result polling.

When the pre-match scrape job stops at kickoff, we register a result-polling
job that hits the Odds API ``/scores`` endpoint until the match is reported
as completed. Once final scores are available, they're written to the
``match_results`` table — joinable with ``odds_snapshots`` for analysis.

Only matches with an ``odds_api_event_id`` are eligible. Obscure-league
matches without an Odds API mapping get a pending row (so we know we tried)
but no polling job; results for those would need a separate ingestion path.
"""
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from apscheduler.triggers.interval import IntervalTrigger

from app.services.odds_tracker.odds_scheduler import scheduler

logger = logging.getLogger(__name__)

# Polling cadence — first fire is delayed to roughly the end of a match,
# then we retry every interval until completed=true or we exceed the budget.
RESULT_FIRST_DELAY_SECONDS = 110 * 60       # 110 min after kickoff
RESULT_POLL_INTERVAL_SECONDS = 10 * 60      # 10 min between polls
RESULT_MAX_POLL_ATTEMPTS = 18               # ≈ 3 hours of polling

# Reused for off-thread blocking calls (httpx + sync DB sessions).
_executor = ThreadPoolExecutor(max_workers=10)


def result_job_id(match_id: str) -> str:
    return f"result_poll_{match_id}"


def _ensure_pending_row_sync(match_id: str, sport: str) -> None:
    """Insert a pending match_results row (sync — runs in thread pool)."""
    try:
        from app.models.database import SessionLocal
        from app.services.odds_tracker.snapshot_persistence import upsert_match_result
        session = SessionLocal()
        try:
            upsert_match_result(session, match_id, sport=sport, completed=False)
        finally:
            session.close()
    except Exception as e:
        logger.warning("Failed to upsert match_result for %s: %s", match_id, e)


def _record_attempt_sync(match_id: str, when: str) -> int:
    try:
        from app.models.database import SessionLocal
        from app.services.odds_tracker.snapshot_persistence import record_poll_attempt
        session = SessionLocal()
        try:
            return record_poll_attempt(session, match_id, when)
        finally:
            session.close()
    except Exception as e:
        logger.warning("Failed to record poll attempt for %s: %s", match_id, e)
        return 0


def _mark_completed_sync(
    match_id: str, sport: str,
    home_score, away_score, when: str,
) -> None:
    try:
        from app.models.database import SessionLocal
        from app.services.odds_tracker.snapshot_persistence import mark_result_completed
        session = SessionLocal()
        try:
            mark_result_completed(
                session, match_id, sport,
                home_score, away_score, fetched_at=when,
            )
        finally:
            session.close()
    except Exception as e:
        logger.warning("Failed to mark result completed for %s: %s", match_id, e)


def _mark_timeout_sync(match_id: str, when: str) -> None:
    try:
        from app.models.database import SessionLocal
        from app.services.odds_tracker.snapshot_persistence import mark_result_timeout
        session = SessionLocal()
        try:
            mark_result_timeout(session, match_id, when)
        finally:
            session.close()
    except Exception as e:
        logger.warning("Failed to mark result timeout for %s: %s", match_id, e)


def _fetch_scores_sync(api_key, sport_key, event_id, home_team, away_team):
    try:
        from app.services.odds_api.odds_api_client import fetch_event_scores
        return fetch_event_scores(api_key, sport_key, event_id, home_team, away_team)
    except Exception as e:
        logger.warning("Score fetch failed for %s: %s", event_id, e)
        return None


def make_result_poll_job(match_id: str):
    """Return an async APScheduler job that polls the Odds API for scores."""

    async def poll_job():
        api_key = os.environ.get("ODDS_API_KEY")
        if not api_key:
            logger.info("ODDS_API_KEY not set — result poll for %s aborted.", match_id)
            scheduler.remove_job(result_job_id(match_id))
            return

        # Pull match meta from the DB (Redis is unreliable here — by the
        # time we run, the pre-match tracker has likely cleared things).
        from app.models.database import SessionLocal
        from app.services.odds_tracker.snapshot_persistence import (
            get_match_meta_from_db, get_match_result_from_db,
        )

        loop = asyncio.get_event_loop()

        meta = await loop.run_in_executor(_executor, _load_meta_sync, match_id)
        if not meta:
            logger.warning("No DB meta for %s — removing result job.", match_id)
            scheduler.remove_job(result_job_id(match_id))
            return

        event_id = meta.get("odds_api_event_id")
        sport_key = meta.get("odds_api_sport_key")
        if not event_id or not sport_key:
            logger.info(
                "Match %s has no odds_api_event_id — cannot poll, removing job.",
                match_id,
            )
            scheduler.remove_job(result_job_id(match_id))
            return

        when = datetime.now(timezone.utc).isoformat()
        attempts = await loop.run_in_executor(
            _executor, _record_attempt_sync, match_id, when,
        )

        scores = await loop.run_in_executor(
            _executor, _fetch_scores_sync,
            api_key, sport_key, event_id,
            meta.get("home_team", ""), meta.get("away_team", ""),
        )

        completed = bool(scores and scores.get("completed"))
        home_score = scores.get("home_score") if scores else None
        away_score = scores.get("away_score") if scores else None

        if completed and home_score is not None and away_score is not None:
            await loop.run_in_executor(
                _executor, _mark_completed_sync,
                match_id, meta.get("sport", "football"),
                home_score, away_score, when,
            )
            scheduler.remove_job(result_job_id(match_id))
            logger.info("Result captured for %s, polling job removed.", match_id)
            return

        if attempts >= RESULT_MAX_POLL_ATTEMPTS:
            await loop.run_in_executor(_executor, _mark_timeout_sync, match_id, when)
            scheduler.remove_job(result_job_id(match_id))
            logger.warning(
                "Result polling for %s gave up after %d attempts.", match_id, attempts,
            )
            return

        logger.info(
            "Match %s not yet completed (attempt %d/%d) — will retry.",
            match_id, attempts, RESULT_MAX_POLL_ATTEMPTS,
        )

    return poll_job


def _load_meta_sync(match_id: str):
    from app.models.database import SessionLocal
    from app.services.odds_tracker.snapshot_persistence import get_match_meta_from_db
    session = SessionLocal()
    try:
        return get_match_meta_from_db(session, match_id)
    finally:
        session.close()


def schedule_result_polling(
    match_id: str,
    sport: str,
    odds_api_event_id: str | None,
    first_run_at: datetime | None = None,
) -> bool:
    """Create the pending result row and (if eligible) register the poll job.

    Returns True when a polling job was scheduled, False when the match is
    only eligible for a pending row (no Odds API mapping).
    """
    # Always create the pending row so downstream queries see an entry.
    asyncio.get_event_loop().run_in_executor(
        _executor, _ensure_pending_row_sync, match_id, sport,
    )

    if not odds_api_event_id:
        logger.info(
            "Match %s has no odds_api_event_id — pending row only, no poll job.",
            match_id,
        )
        return False

    if first_run_at is None:
        first_run_at = datetime.now(timezone.utc)

    scheduler.add_job(
        make_result_poll_job(match_id),
        trigger=IntervalTrigger(seconds=RESULT_POLL_INTERVAL_SECONDS),
        id=result_job_id(match_id),
        replace_existing=True,
        next_run_time=first_run_at,
    )
    logger.info(
        "Result polling job registered for %s (first run %s).",
        match_id, first_run_at.isoformat(),
    )
    return True


def stop_result_job(match_id: str) -> bool:
    """Manually remove a result-polling job, if scheduled."""
    jid = result_job_id(match_id)
    if scheduler.get_job(jid):
        scheduler.remove_job(jid)
        return True
    return False
