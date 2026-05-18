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

from app.core.auth import get_current_user, require_role
from app.core.config import redis_client, rate_limit_dependency
from app.core.quotas import (
    CONCURRENT_TRACKER_LIMIT,
    DAILY_TRACK_LIMIT,
    TRACK_KICKOFF_LOOKAHEAD_SECONDS,
    TRACK_POLL_INTERVAL_SECONDS,
    normalize_role,
)
from app.models.markets import (
    DEFAULT_MARKETS,
    MARKET_1X2,
    MARKET_LABELS,
    MARKET_LINE,
    SUPPORTED_MARKETS,
    is_supported,
    outcomes_for,
)
from app.models.odds_models import TrackedMatch
from app.models.users import User
# from app.models.odds import MatchData, Outcome, H2HMarket, Bookmaker
from dotenv import load_dotenv
from app.models.sport import SportType
from app.services.flashscore_scraper.scraper_factory import get_scraper
from app.services.odds_tracker.odds_tracker import (
    register_match, is_already_tracked,
    get_all_tracked_ids, get_match_meta,
    get_odds_history,unregister_match,
)
from app.services.odds_tracker.odds_scheduler import start_tracking_job, scheduler, stop_tracking_job
from app.core.config import SCRAPE_INTERVAL_SECONDS
from app.services.odds_tracker.odds_tracker import store_odds_snapshot
from app.services.odds_tracker.primary_odds import decorate_history, resolve_primary_odds
from app.models.database import SessionLocal
from app.services.odds_tracker.snapshot_persistence import (
    get_match_snapshots as db_get_snapshots,
    get_match_meta_from_db,
    get_all_matches_from_db,
    get_match_result_from_db,
    upsert_match_result,
    mark_result_completed,
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
    sport_key: Optional[str] = None  # e.g. "soccer_epl", "tennis_atp_miami_open"
    sport: SportType = SportType.FOOTBALL  # Defaults to football for backward compatibility
    # Markets to track for this match. Validated against
    # ``SUPPORTED_MARKETS``; an empty / missing value defaults to
    # ``DEFAULT_MARKETS`` (1X2 only) so legacy clients keep working.
    # Tennis ignores anything other than 1x2 — see /track body for the
    # explicit override.
    markets: Optional[list[str]] = None

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
        """Resolve aliases ('champions_league' → 'soccer_uefa_champs_league')
        and reject invalid/placeholder values like 'string'."""
        from app.services.odds_api.odds_api_client import resolve_sport_key
        return resolve_sport_key(v)

    @field_validator("markets", mode="before")
    @classmethod
    def sanitize_markets(cls, v):
        """Drop unknown / empty values; preserve order, dedupe. None means
        'use the default' — let the route handler apply it so the source
        of truth lives in one place."""
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError("markets must be a list of strings.")
        seen: set[str] = set()
        ordered: list[str] = []
        for m in v:
            if not isinstance(m, str):
                continue
            m = m.strip()
            if not m or m in seen:
                continue
            if not is_supported(m):
                raise ValueError(
                    f"Unsupported market '{m}'. Allowed: {sorted(SUPPORTED_MARKETS)}",
                )
            seen.add(m)
            ordered.append(m)
        return ordered or None

    def validate_inputs(self):
        """Raises ValueError with a clear message if inputs are unusable."""
        if self.match_id:
            return  # match_id is always sufficient
        if self.sport == SportType.FOOTBALL and not self.home_team:
            raise ValueError("Provide either 'home_team' or 'match_id' for football.")
        if self.sport == SportType.TENNIS and not self.player_name and not self.home_team:
            raise ValueError("Provide either 'player_name' or 'match_id' for tennis.")


@router.post("/track")
async def track_match(
    body: TrackRequest,
    redis_client=Depends(get_redis),
    user: User = Depends(get_current_user),
):
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
    # Step 2b — Tier checks (PR2): daily new-track count + concurrent cap.
    # Run BEFORE the expensive FlashScore scrape so a quota-blocked user
    # doesn't burn ~5s of scraper time. The kickoff-lookahead check
    # happens after meta resolution because it needs start_time.
    # ------------------------------------------------------------------
    role = normalize_role(user.role)
    daily_track_cap = DAILY_TRACK_LIMIT[role]
    daily_track_key = f"daily_tracks:{user.firebase_uid}"
    if daily_track_cap != -1:
        current_raw = await redis_client.get(daily_track_key)
        current_daily_tracks = int(current_raw) if current_raw else 0
        if current_daily_tracks >= daily_track_cap:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Daily tracking limit reached ({daily_track_cap}/day for "
                    f"{role} tier). Resets in 24h or upgrade for more."
                ),
            )

    concurrent_cap = CONCURRENT_TRACKER_LIMIT[role]
    if concurrent_cap != -1:
        session_q = SessionLocal()
        try:
            active_count = (
                session_q.query(TrackedMatch)
                .filter(TrackedMatch.user_id == user.id, TrackedMatch.status == "tracking")
                .count()
            )
        finally:
            session_q.close()
        if active_count >= concurrent_cap:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"You already have {active_count}/{concurrent_cap} concurrent "
                    f"trackers running ({role} tier). Untrack one to free a slot, "
                    "or upgrade for more."
                ),
            )

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
                event_id, sport_key_resolved, commence_time = result
                meta["odds_api_event_id"] = event_id
                meta["odds_api_sport_key"] = sport_key_resolved
                if commence_time:
                    # The Odds API returns proper UTC ISO 8601 (e.g. "2026-04-26T19:00:00Z").
                    # Prefer it over the FlashScore-scraped time, which can drift by
                    # the GCE VM's IP-geolocated tz (CEST → +2h skew).
                    fs_start = meta.get("start_time")
                    meta["start_time"] = commence_time
                    meta["start_time_source"] = "odds_api"
                    if fs_start and fs_start != commence_time:
                        logger.info(
                            "Step 5: Overrode FlashScore start_time %s with Odds API commence_time %s",
                            fs_start, commence_time,
                        )
                else:
                    meta["start_time_source"] = "flashscore"
                logger.info(
                    "Step 5: Mapped to Odds API event %s (%s) commence_time=%s",
                    event_id, sport_key_resolved, commence_time,
                )
            else:
                meta["start_time_source"] = "flashscore"
                logger.info("Step 5: No matching Odds API event found.")
        except Exception as e:
            meta["start_time_source"] = "flashscore"
            logger.warning("Step 5: Odds API lookup failed: %s", e)
    else:
        meta["start_time_source"] = "flashscore"

    # ------------------------------------------------------------------
    # Step 5b — Kickoff lookahead check (PR2). Now that we have the
    # authoritative start_time (Odds API > FlashScore), enforce the
    # tier's lookahead window. Doing it here avoids registering and
    # then immediately tearing down a tracker we'd reject anyway.
    # ------------------------------------------------------------------
    max_lookahead = TRACK_KICKOFF_LOOKAHEAD_SECONDS[role]
    if max_lookahead != -1 and meta.get("start_time"):
        try:
            kickoff_dt = datetime.fromisoformat(meta["start_time"].replace("Z", "+00:00"))
            if kickoff_dt.tzinfo is None:
                kickoff_dt = kickoff_dt.replace(tzinfo=timezone.utc)
            seconds_to_kickoff = (kickoff_dt - datetime.now(timezone.utc)).total_seconds()
            if seconds_to_kickoff > max_lookahead:
                hours_allowed = max_lookahead // 3600
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Kickoff is too far in the future for your tier "
                        f"({role}: max {hours_allowed}h ahead). Upgrade to track "
                        "matches further out."
                    ),
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Kickoff lookahead check skipped (parse failed): %s", e)

    # Stamp owner + per-tier poll cadence onto meta so persist_match() writes
    # them and the post-restart recovery path can re-schedule at the right rate.
    # ``user_id`` is stored as a string because the meta dict is JSON-encoded
    # to Redis; SQLAlchemy still accepts the string into the UUID column.
    poll_interval = TRACK_POLL_INTERVAL_SECONDS[role]
    meta["user_id"] = str(user.id)
    meta["poll_interval_seconds"] = poll_interval

    # Resolve the markets the user wants tracked. Tennis is 1X2-only, so
    # we override any other selection — clearer than rejecting the request.
    if sport == SportType.TENNIS:
        meta["markets"] = [MARKET_1X2]
    else:
        meta["markets"] = body.markets or list(DEFAULT_MARKETS)
    logger.info("Step 5: markets resolved → %s", meta["markets"])

    await register_match(redis_client, match_id, meta)
    logger.info("Step 5 complete: meta stored (poll_interval=%ds).", poll_interval)

    # ------------------------------------------------------------------
    # Step 6 — Store initial odds snapshot per configured market.
    # The 1X2 snapshot reuses the data we already scraped during meta
    # resolution. Non-1X2 markets need a fresh scrape because the
    # FlashScore endpoint is different per market. We do the extra
    # scrapes inline (synchronously, in a thread pool) so the user sees
    # data on the chart immediately on the next /history call — without
    # this, they'd wait a full poll_interval (10–45 min) before the first
    # O/U snapshot exists.
    # ------------------------------------------------------------------
    for market in meta["markets"]:
        if market == MARKET_1X2:
            # Already scraped during meta resolution.
            if sport == SportType.TENNIS:
                has_initial = initial_odds.get("player1") is not None
            else:
                has_initial = initial_odds.get("home") is not None
            if not has_initial:
                logger.info("Step 6: No valid initial 1X2 odds yet for %s.", match_id)
                continue
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
                market=MARKET_1X2,
            )
            logger.info("Step 6: Initial 1X2 snapshot stored.")
        else:
            try:
                market_odds = await loop.run_in_executor(
                    None, scraper.get_odds_by_market, match_id, market,
                )
                if market_odds.get("over") is None:
                    logger.info(
                        "Step 6: No valid initial odds yet for %s on %s.",
                        match_id, market,
                    )
                    continue
                await store_odds_snapshot(
                    redis_client, match_id, market_odds,
                    sport=sport.value,
                    sharp_odds=None,
                    market=market,
                )
                logger.info("Step 6: Initial %s snapshot stored.", market)
            except Exception as e:
                # One bad market shouldn't block the whole /track call.
                logger.warning(
                    "Step 6: Initial scrape for market %s failed: %s",
                    market, e,
                )

    # ------------------------------------------------------------------
    # Step 7 — Start scheduler at the user's tier-specific cadence.
    # ------------------------------------------------------------------
    start_tracking_job(
        match_id, scraper, redis_client,
        sport=sport.value,
        poll_interval_seconds=poll_interval,
    )
    logger.info("Step 7: Scheduler job registered (poll_interval=%ds).", poll_interval)

    # ------------------------------------------------------------------
    # Step 8 — Charge against the user's daily track quota. Done last so
    # a request that fails earlier (e.g. scrape error → 500) doesn't
    # consume the slot. SET with 24h TTL on first use of the day, INCR
    # otherwise so the existing TTL is preserved.
    # ------------------------------------------------------------------
    if daily_track_cap != -1:
        post_raw = await redis_client.get(daily_track_key)
        if post_raw is None:
            await redis_client.set(daily_track_key, 1, ex=86400)
        else:
            await redis_client.incr(daily_track_key)

    return {
        "match_id": match_id,
        "sport": sport.value,
        "status": "tracking_started",
        "meta": meta,
        "message": f"Tracking {sport.value} odds every {poll_interval}s until kickoff.",
    }

@router.get("/tracked")
async def list_tracked_matches(
    redis_client=Depends(get_redis),
    user: User = Depends(get_current_user),
):
    """Return the caller's currently tracked match IDs with their metadata.

    Each tracker's owner is stored on the meta dict at /odds/track time
    (meta["user_id"]). We filter against that here so users only see their
    own active trackers.
    """
    match_ids = await get_all_tracked_ids(redis_client)

    if not match_ids:
        return {"tracked_matches": [], "count": 0}

    owner_id = str(user.id)
    matches = []
    for match_id in match_ids:
        meta = await get_match_meta(redis_client, match_id)
        # Skip matches with no owner stamp (legacy data) or owned by someone else.
        if not meta or str(meta.get("user_id") or "") != owner_id:
            continue
        matches.append({
            "match_id": match_id,
            "meta": meta,
            # Convenience: is the scheduler job still active?
            "job_active": scheduler.get_job(f"odds_scrape_{match_id}") is not None,
        })

    return {"tracked_matches": matches, "count": len(matches)}


@router.get("/matches")
async def list_all_matches(
    redis_client=Depends(get_redis),
    user: User = Depends(get_current_user),
):
    """
    Return matches the caller has tracked (from PostgreSQL), enriched with
    live status from Redis when available. Filtered server-side by user_id —
    other users' trackers are never returned.
    """
    session = SessionLocal()
    try:
        db_matches = get_all_matches_from_db(session, user_id=str(user.id))
    finally:
        session.close()

    # Enrich with live tracking status from Redis
    active_ids = set(await get_all_tracked_ids(redis_client))

    results = []
    for m in db_matches:
        match_id = m["match_id"]
        job_active = scheduler.get_job(f"odds_scrape_{match_id}") is not None
        results.append({
            "match_id": match_id,
            "meta": m,
            "job_active": job_active,
            "is_live": match_id in active_ids,
        })

    return {"matches": results, "count": len(results)}


@router.get("/history/{match_id}")
async def stream_odds_history(
        match_id: str,
        redis_client=Depends(get_redis),
        user: User = Depends(get_current_user),
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

    # Ownership check — Flashscore match IDs are guessable, so without this a
    # URL like /api/odds/history/XYZ would expose another user's stream.
    if str(meta.get("user_id") or "") != str(user.id):
        raise HTTPException(
            status_code=404,
            detail=f"Match {match_id} is not tracked. Start tracking via POST /odds/track.",
        )

    async def event_stream():
        # --- 1. Send match metadata as first event ---
        yield f"data: {json.dumps({'type': 'meta', 'data': meta})}\n\n"

        # --- 2. Replay full existing history (decorated with primary_odds) ---
        history = await get_odds_history(redis_client, match_id)
        decorated = decorate_history(history)
        last_sent_count = len(decorated)

        for snapshot in decorated:
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

            if len(history) > last_sent_count:
                # Re-decorate everything so the new tail's change deltas are
                # computed against the correct previous primary_odds.
                decorated = decorate_history(history)
                for snapshot in decorated[last_sent_count:]:
                    yield f"data: {json.dumps({'type': 'snapshot', 'data': snapshot})}\n\n"
                last_sent_count = len(decorated)
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


@router.get("/markets")
async def list_supported_markets() -> dict:
    """Static catalogue of markets this build of the API knows how to
    scrape + render. Frontend uses it to populate the per-match checkbox
    set without hard-coding the list. Public — no auth — so unauthed
    pricing pages can show "tracks O/U 2.5" without a token round-trip.
    """
    return {
        "markets": [
            {
                "id": m,
                "label": MARKET_LABELS.get(m, m),
                "outcomes": list(outcomes_for(m)),
                "line": MARKET_LINE.get(m),
                "is_default": m in DEFAULT_MARKETS,
            }
            for m in SUPPORTED_MARKETS
        ],
    }


@router.get("/history/{match_id}/summary")
async def get_match_history_summary(
    match_id: str,
    market: str = Query(default=MARKET_1X2, description="Market id (e.g. '1x2', 'ou_2.5')"),
    redis_client=Depends(get_redis),
    user: User = Depends(get_current_user),
):
    # Validate market early — keeps Redis lookups from happening with a
    # garbage key and produces a clear 422 instead of an empty history.
    if not is_supported(market):
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported market '{market}'. Allowed: {sorted(SUPPORTED_MARKETS)}",
        )

    # 1. Try Redis first (fast, real-time data) — market-scoped key.
    meta = await get_match_meta(redis_client, match_id)
    history = await get_odds_history(redis_client, match_id, market=market)

    # 2. Fallback to PostgreSQL when Redis data is gone
    if not history:
        logger.info(
            "Redis empty for %s on market %s — falling back to PostgreSQL.",
            match_id, market,
        )
        session = SessionLocal()
        try:
            if not meta:
                meta = get_match_meta_from_db(session, match_id)
            history = db_get_snapshots(session, match_id, market=market)
        finally:
            session.close()

    if not meta and not history:
        return {
            "match_id": match_id,
            "market": market,
            "history": [],
            "message": "No snapshots recorded yet.",
        }

    # Ownership check — same rationale as the SSE stream above. We hit Redis
    # then DB to resolve meta, and only enforce ownership once we know which
    # user owns the row.
    owner = str((meta or {}).get("user_id") or "")
    if owner and owner != str(user.id):
        raise HTTPException(
            status_code=404,
            detail=f"Match {match_id} is not tracked.",
        )

    if not meta:
        meta = {}

    decorated_history = decorate_history(history)
    processed_history = []

    for i, snapshot in enumerate(decorated_history):
        current_time = datetime.fromisoformat(snapshot["timestamp"])

        # Calculate interval since the previous snapshot
        if i > 0:
            prev_time = datetime.fromisoformat(decorated_history[i - 1]["timestamp"])
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
        "market": market,
        "match": match_label,
        "start_time": meta.get("start_time"),
        "total_snapshots": len(processed_history),
        "history": processed_history,
        # Surface the configured markets so the frontend tab strip can render
        # without an extra round-trip.
        "configured_markets": (meta or {}).get("markets") or list(DEFAULT_MARKETS),
    }

# odds.py — add this route after /tracked

@router.delete("/untrack/{match_id}")
async def untrack_match(
    match_id: str,
    redis_client=Depends(get_redis),
    user: User = Depends(get_current_user),
):
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

    # Ownership check — only the user who registered the tracker can stop it.
    # Returns 404 (not 403) so we don't reveal that the match exists under
    # another owner.
    if str(meta.get("user_id") or "") != str(user.id):
        raise HTTPException(
            status_code=404,
            detail=f"Match '{match_id}' is not tracked.",
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


@router.post("/result/{match_id}/refresh")
async def refresh_match_result(
    match_id: str,
    user: User = Depends(get_current_user),
):
    """Force an immediate Odds API scores fetch for a match.

    Useful after a result poll timed out, or to backfill a result that the
    scheduler missed (e.g., the server was down during the polling window).
    """
    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ODDS_API_KEY not configured.")

    session = SessionLocal()
    try:
        match_meta = get_match_meta_from_db(session, match_id)
    finally:
        session.close()

    if not match_meta:
        raise HTTPException(status_code=404, detail=f"Match {match_id} not found.")

    event_id = match_meta.get("odds_api_event_id")
    sport_key = match_meta.get("odds_api_sport_key")
    if not event_id or not sport_key:
        raise HTTPException(
            status_code=409,
            detail=f"Match {match_id} has no Odds API mapping; cannot fetch scores.",
        )

    loop = asyncio.get_event_loop()
    from app.services.odds_api.odds_api_client import fetch_event_scores
    scores = await loop.run_in_executor(
        None, fetch_event_scores, api_key, sport_key, event_id,
        match_meta.get("home_team", ""), match_meta.get("away_team", ""),
    )

    when = datetime.now(timezone.utc).isoformat()
    if scores and scores.get("completed") and scores.get("home_score") is not None:
        session = SessionLocal()
        try:
            mark_result_completed(
                session, match_id, sport=match_meta.get("sport", "football"),
                home_score=scores["home_score"], away_score=scores["away_score"],
                fetched_at=when,
            )
            # Stop any still-running polling job — we have the answer.
            from app.services.odds_tracker.result_scheduler import stop_result_job
            stop_result_job(match_id)
            result = get_match_result_from_db(session, match_id)
        finally:
            session.close()
        return {"match_id": match_id, "status": "completed", "result": result}

    return {
        "match_id": match_id,
        "status": "pending",
        "scores_response": scores,
        "message": "Match not yet completed in Odds API scores feed.",
    }


@router.get("/match/{match_id}/dataset")
async def get_match_dataset(
    match_id: str,
    redis_client=Depends(get_redis),
    _admin: User = Depends(require_role("admin")),
):
    """Return the structured per-match dataset: meta + snapshots + result.

    Snapshots come from PostgreSQL (or Redis if DB is empty), each enriched
    with primary_odds/primary_change from the same resolver used elsewhere,
    so a downstream notebook sees identical fields to the live UI.
    """
    session = SessionLocal()
    try:
        match_meta = get_match_meta_from_db(session, match_id)
        if not match_meta:
            redis_meta = await get_match_meta(redis_client, match_id)
            if not redis_meta:
                raise HTTPException(status_code=404, detail=f"Match {match_id} not found.")
            match_meta = redis_meta

        snapshots = db_get_snapshots(session, match_id)
        if not snapshots:
            snapshots = await get_odds_history(redis_client, match_id)

        result = get_match_result_from_db(session, match_id)
    finally:
        session.close()

    decorated = decorate_history(snapshots)

    return {
        "match_id": match_id,
        "meta": match_meta,
        "snapshots": decorated,
        "snapshot_count": len(decorated),
        "result": result,
    }


@router.delete("/untrack/all")
async def untrack_all_matches(
    redis_client=Depends(get_redis),
    _admin: User = Depends(require_role("admin")),
):
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
