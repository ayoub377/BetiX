import asyncio
import json
import logging
import os
from typing import List, Optional
import re

import shin
from fastapi import APIRouter, HTTPException, Depends, Query
import requests
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

# from app.core.auth import has_access
from app.core.config import redis_client, rate_limit_dependency
# from app.models.odds import MatchData, Outcome, H2HMarket, Bookmaker
from dotenv import load_dotenv
from app.models.sport import SportType
from app.services.flashscore_scraper.scraper_factory import get_scraper
from app.services.flashscore_scraper.flashscore_scraper import FlashScoreScraper
from app.services.odds_tracker.odds_tracker import (
    register_match, is_already_tracked,
    get_all_tracked_ids, get_match_meta,
    get_odds_history,unregister_match,
)
from app.services.odds_tracker.odds_scheduler import start_tracking_job, scheduler, stop_tracking_job
from app.core.config import SCRAPE_INTERVAL_SECONDS
from app.services.odds_tracker.odds_tracker import store_odds_snapshot
from app.models.database import SessionLocal
from app.services.odds_tracker.snapshot_persistence import (
    get_match_snapshots as db_get_snapshots,
    get_match_meta_from_db,
)

load_dotenv()
router = APIRouter()


# league = ''
# API_KEY = os.getenv("ODDS_API_KEY")
def get_redis():
    return redis_client


# Cache expiry time in seconds (30 minutes)
CACHE_EXPIRY = 30 * 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


_FLASHSCORE_ID_RE = re.compile(r'^[A-Za-z0-9]{8,}$')


class TrackRequest(BaseModel):
    home_team: Optional[str] = None
    player_name: Optional[str] = None  # Tennis: alternative to home_team
    match_id: Optional[str] = None
    sport_key: Optional[str] = None  # e.g. "soccer_epl" — helps Odds API event lookup
    sport: SportType = SportType.FOOTBALL  # Defaults to football for backward compatibility

    @field_validator("match_id", mode="before")
    @classmethod
    def sanitize_match_id(cls, v):
        """Treat empty / Swagger-default / non-FlashScore-format values as absent."""
        if not v or not _FLASHSCORE_ID_RE.match(str(v).strip()):
            return None
        return str(v).strip()

    @field_validator("sport_key", mode="before")
    @classmethod
    def sanitize_sport_key(cls, v):
        """Ignore Swagger placeholder values — sport_key must look like 'soccer_epl'."""
        from app.services.odds_api.odds_api_client import _is_valid_sport_key
        if not _is_valid_sport_key(v):
            return None
        return str(v).strip()

    def validate_inputs(self):
        """Raises ValueError with a clear message if inputs are unusable."""
        if self.match_id:
            return  # match_id is always sufficient
        if self.sport == SportType.FOOTBALL and not self.home_team:
            raise ValueError("Provide either 'home_team' or 'match_id' for football.")
        if self.sport == SportType.TENNIS and not self.player_name and not self.home_team:
            raise ValueError("Provide either 'player_name' or 'match_id' for tennis.")


@router.post("/track")
async def track_match(body: TrackRequest, redis_client=Depends(get_redis)):
    logger.info("=== /odds/track called with body: %s", body)

    try:
        body.validate_inputs()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    loop = asyncio.get_event_loop()
    sport = body.sport
    scraper = get_scraper(sport, persist_outputs=False)
    match_id = body.match_id

    # ------------------------------------------------------------------
    # Step 1 — Resolve match_id from participant name if not provided
    # ------------------------------------------------------------------
    if not match_id:
        participant_name = body.player_name or body.home_team
        logger.info("Step 1: Resolving match_id from participant='%s' (sport=%s)", participant_name, sport.value)
        try:
            if sport == SportType.TENNIS:
                match_id = await loop.run_in_executor(
                    None, scraper.get_player_id_by_name, participant_name
                )
            else:
                match_id = await loop.run_in_executor(
                    None, scraper.get_team_id_by_name, participant_name
                )
            logger.info("Step 1 complete: resolved match_id='%s'", match_id)
        except Exception as e:
            logger.error("Step 1 FAILED: %s", e, exc_info=True)
            raise HTTPException(status_code=404, detail=f"Could not resolve name: {e}")

        if not match_id:
            raise HTTPException(
                status_code=404,
                detail=f"No upcoming match found for '{participant_name}'."
            )
    else:
        logger.info("Step 1: Using provided match_id='%s' directly.", match_id)

    # ------------------------------------------------------------------
    # Step 2 — Already tracked?
    # ------------------------------------------------------------------
    if await is_already_tracked(redis_client, match_id):
        meta = await get_match_meta(redis_client, match_id)
        logger.info("Step 2: Already tracked, returning early.")
        return {"match_id": match_id, "status": "already_tracked", "meta": meta}

    # ------------------------------------------------------------------
    # Step 3 — Scrape match info
    # ------------------------------------------------------------------
    logger.info("Step 3: Fetching match info for match_id='%s' (sport=%s)", match_id, sport.value)
    try:
        match_info = await loop.run_in_executor(None, scraper.get_match_info, match_id)
        logger.info("Step 3 complete: match_info=%s", match_info)
    except Exception as e:
        logger.error("Step 3 FAILED: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not fetch match info: {e}")

    # Reject if match info came back empty — means the match_id is invalid
    if sport == SportType.TENNIS:
        info_empty = match_info.get("player1") == "unknown" and match_info.get("start_time") is None
    else:
        info_empty = match_info.get("home_team") == "unknown" and match_info.get("start_time") is None

    if info_empty:
        raise HTTPException(
            status_code=404,
            detail=(
                f"match_id '{match_id}' returned no data from FlashScore. "
                "Check the ID is correct and the match exists."
            )
        )

    # ------------------------------------------------------------------
    # Step 4 — Scrape initial odds snapshot
    # ------------------------------------------------------------------
    logger.info("Step 4: Fetching initial odds for match_id='%s'", match_id)
    try:
        initial_odds = await loop.run_in_executor(
            None,
            scraper.get_odds_by_match_id,
            match_id
        )
        logger.info("Step 4 complete: initial_odds=%s", initial_odds)
    except Exception as e:
        logger.warning("Step 4 WARNING: %s — continuing without initial odds.", e)
        initial_odds = {}

    # ------------------------------------------------------------------
    # Step 5 — Register in Redis + resolve Odds API event (sport-aware metadata)
    # ------------------------------------------------------------------
    if sport == SportType.TENNIS:
        meta = {
            "match_id": match_id,
            "sport": sport.value,
            "player1": match_info.get("player1", "unknown"),
            "player2": match_info.get("player2", "unknown"),
            # Backward-compatible aliases
            "home_team": match_info.get("player1", "unknown"),
            "away_team": match_info.get("player2", "unknown"),
            "start_time": match_info.get("start_time"),
            "start_time_raw": match_info.get("start_time_raw"),
            "status": "tracking",
            "tracked_since": datetime.now(timezone.utc).isoformat(),
        }
    else:
        home_team = match_info.get("home_team", body.home_team or "unknown")
        away_team = match_info.get("away_team", "unknown")
        meta = {
            "match_id": match_id,
            "sport": sport.value,
            "home_team": home_team,
            "away_team": away_team,
            "start_time": match_info.get("start_time"),
            "start_time_raw": match_info.get("start_time_raw"),
            "status": "tracking",
            "tracked_since": datetime.now(timezone.utc).isoformat(),
        }

    # Try to resolve matching Odds API event (optional — needs ODDS_API_KEY)
    odds_api_key = os.getenv("ODDS_API_KEY")
    if odds_api_key:
        try:
            from app.services.odds_api.odds_api_client import find_event
            result = await loop.run_in_executor(
                None, find_event, odds_api_key,
                meta.get("home_team", ""), meta.get("away_team", ""),
                body.sport_key, sport.value,
            )
            if result:
                meta["odds_api_event_id"] = result[0]
                meta["odds_api_sport_key"] = result[1]
                logger.info("Step 5: Mapped to Odds API event %s (%s)", result[0], result[1])
            else:
                logger.info("Step 5: No matching Odds API event found.")
        except Exception as e:
            logger.warning("Step 5: Odds API lookup failed: %s", e)

    await register_match(redis_client, match_id, meta)
    logger.info("Step 5 complete: meta stored.")

    # ------------------------------------------------------------------
    # Step 6 — Store initial odds snapshot (with sharp odds if available)
    # ------------------------------------------------------------------
    if sport == SportType.TENNIS:
        has_initial = initial_odds.get("player1") is not None
    else:
        has_initial = initial_odds.get("home") is not None

    if has_initial:
        initial_sharp_odds = None
        if odds_api_key and meta.get("odds_api_event_id"):
            try:
                from app.services.odds_api.odds_api_client import fetch_sharp_odds
                initial_sharp_odds = await loop.run_in_executor(
                    None, fetch_sharp_odds,
                    odds_api_key, meta["odds_api_sport_key"],
                    meta["odds_api_event_id"],
                    meta.get("home_team", ""), meta.get("away_team", ""),
                )
            except Exception as e:
                logger.warning("Step 6: Sharp odds fetch failed: %s", e)

        await store_odds_snapshot(
            redis_client, match_id, initial_odds,
            sport=sport.value,
            sharp_odds=initial_sharp_odds or None,
        )
        logger.info("Step 6: Initial snapshot stored.")
    else:
        logger.info("Step 6: No valid initial odds yet.")

    # ------------------------------------------------------------------
    # Step 7 — Start scheduler
    # ------------------------------------------------------------------
    start_tracking_job(match_id, scraper, redis_client, sport=sport.value)
    logger.info("Step 7: Scheduler job registered.")

    return {
        "match_id": match_id,
        "sport": sport.value,
        "status": "tracking_started",
        "meta": meta,
        "message": f"Tracking {sport.value} odds every {SCRAPE_INTERVAL_SECONDS}s until kickoff.",
    }

@router.get("/tracked")
async def list_tracked_matches(redis_client=Depends(get_redis)):
    """Return all currently tracked match IDs with their metadata."""
    match_ids = await get_all_tracked_ids(redis_client)

    if not match_ids:
        return {"tracked_matches": [], "count": 0}

    matches = []
    for match_id in match_ids:
        meta = await get_match_meta(redis_client, match_id)
        matches.append({
            "match_id": match_id,
            "meta": meta,
            # Convenience: is the scheduler job still active?
            "job_active": scheduler.get_job(f"odds_scrape_{match_id}") is not None,
        })

    return {"tracked_matches": matches, "count": len(matches)}


@router.get("/history/{match_id}")
async def stream_odds_history(
        match_id: str,
        redis_client=Depends(get_redis),
        poll_interval: int = Query(default=10, ge=5, le=60,
                                   description="How often (seconds) to check for new snapshots"),
):
    """
    Stream odds history for a tracked match as Server-Sent Events.

    - Immediately sends all existing snapshots on connect.
    - Then polls Redis for new snapshots and pushes them as they arrive.
    - Sends keepalive every poll_interval seconds when no new data.
    - Closes automatically when tracking stops (match completed/removed).
    """
    meta = await get_match_meta(redis_client, match_id)
    if not meta:
        raise HTTPException(
            status_code=404,
            detail=f"Match {match_id} is not tracked. Start tracking via POST /odds/track."
        )

    async def event_stream():
        # --- 1. Send match metadata as first event ---
        yield f"data: {json.dumps({'type': 'meta', 'data': meta})}\n\n"

        # --- 2. Replay full existing history ---
        history = await get_odds_history(redis_client, match_id)
        last_sent_count = len(history)

        for snapshot in history:
            yield f"data: {json.dumps({'type': 'snapshot', 'data': snapshot})}\n\n"

        yield f"data: {json.dumps({'type': 'history_complete', 'count': last_sent_count})}\n\n"

        # --- 3. Poll for new snapshots ---
        import asyncio
        while True:
            await asyncio.sleep(poll_interval)

            current_meta = await get_match_meta(redis_client, match_id)

            # Tracking ended — send final event and close
            if not current_meta or current_meta.get("status") == "completed":
                yield f"data: {json.dumps({'type': 'tracking_ended', 'match_id': match_id})}\n\n"
                break

            history = await get_odds_history(redis_client, match_id)
            new_snapshots = history[last_sent_count:]

            if new_snapshots:
                for snapshot in new_snapshots:
                    yield f"data: {json.dumps({'type': 'snapshot', 'data': snapshot})}\n\n"
                last_sent_count = len(history)
            else:
                # Keepalive so the connection doesn't time out
                yield f"data: {json.dumps({'type': 'keepalive', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering for SSE
        }
    )


@router.get("/history/{match_id}/summary")
async def get_match_history_summary(match_id: str, redis_client=Depends(get_redis)):
    # 1. Try Redis first (fast, real-time data)
    meta = await get_match_meta(redis_client, match_id)
    history = await get_odds_history(redis_client, match_id)

    # 2. Fallback to PostgreSQL when Redis data is gone
    if not history:
        logger.info("Redis empty for %s — falling back to PostgreSQL.", match_id)
        session = SessionLocal()
        try:
            if not meta:
                meta = get_match_meta_from_db(session, match_id)
            history = db_get_snapshots(session, match_id)
        finally:
            session.close()

    if not meta and not history:
        return {"match_id": match_id, "history": [], "message": "No snapshots recorded yet."}

    if not meta:
        meta = {}

    processed_history = []

    for i, snapshot in enumerate(history):
        current_time = datetime.fromisoformat(snapshot["timestamp"])

        # Calculate interval since the previous snapshot
        if i > 0:
            prev_time = datetime.fromisoformat(history[i - 1]["timestamp"])
            interval_seconds = (current_time - prev_time).total_seconds()
        else:
            interval_seconds = 0  # First entry has no previous interval

        # Add the interval data to the snapshot object
        snapshot_with_interval = {
            **snapshot,
            "seconds_since_last": interval_seconds,
            "display_interval": f"{int(interval_seconds)}s" if i > 0 else "Initial"
        }
        processed_history.append(snapshot_with_interval)

    # Sport-aware match label
    sport = meta.get("sport", "football") if meta else "football"
    if sport == "tennis":
        match_label = f"{meta.get('player1', meta.get('home_team'))} vs {meta.get('player2', meta.get('away_team'))}"
    else:
        match_label = f"{meta.get('home_team', 'unknown')} vs {meta.get('away_team', 'unknown')}"

    return {
        "sport": sport,
        "match": match_label,
        "start_time": meta.get("start_time"),
        "total_snapshots": len(processed_history),
        "history": processed_history
    }

# odds.py — add this route after /tracked

@router.delete("/untrack/{match_id}")
async def untrack_match(match_id: str, redis_client=Depends(get_redis)):
    """
    Stop tracking a match and remove it from the scheduler.
    History is preserved in Redis — only active tracking stops.
    """
    meta = await get_match_meta(redis_client, match_id)

    if not meta:
        raise HTTPException(
            status_code=404,
            detail=f"Match '{match_id}' is not tracked."
        )

    # Stop the scheduler job
    stop_tracking_job(match_id)

    # Remove from Redis tracking index + mark as completed
    await unregister_match(redis_client, match_id)

    logger.info("Manually untracked match %s", match_id)

    return {
        "match_id": match_id,
        "status": "untracked",
        "message": f"Match {match_id} removed from tracking. History preserved.",
    }


@router.delete("/untrack/all")
async def untrack_all_matches(redis_client=Depends(get_redis)):
    """
    Stop tracking ALL matches at once. Useful for cleanup.
    History is preserved — only active tracking stops.
    """
    match_ids = await get_all_tracked_ids(redis_client)

    if not match_ids:
        return {"status": "nothing_to_untrack", "count": 0}

    removed = []
    failed = []

    for match_id in match_ids:
        try:
            stop_tracking_job(match_id)
            await unregister_match(redis_client, match_id)
            removed.append(match_id)
            logger.info("Untracked match %s", match_id)
        except Exception as e:
            logger.error("Failed to untrack match %s: %s", match_id, e)
            failed.append({"match_id": match_id, "error": str(e)})

    return {
        "status": "done",
        "removed": removed,
        "failed": failed,
        "count_removed": len(removed),
    }
