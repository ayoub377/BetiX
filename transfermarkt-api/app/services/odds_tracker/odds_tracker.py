import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.models.markets import MARKET_1X2

logger = logging.getLogger(__name__)


# Redis key helpers — single place to change key shapes
def match_meta_key(match_id: str) -> str:
    return f"tracked_match:{match_id}"


def odds_history_key(match_id: str, market: str = MARKET_1X2) -> str:
    """Redis list key for a match's odds history on a given market.

    The 1X2 key keeps its legacy shape (``odds_history:<id>``) so any
    in-flight Redis data from before the multi-market change still loads
    seamlessly. Other markets get a suffix (e.g. ``odds_history:<id>:ou_2.5``).
    """
    if market == MARKET_1X2:
        return f"odds_history:{match_id}"
    return f"odds_history:{match_id}:{market}"


TRACKED_INDEX_KEY = "tracked_matches_index"


def _persist_snapshot_to_db(match_id: str, snapshot: dict):
    """Write a snapshot to PostgreSQL. Runs in a thread — must be sync."""
    try:
        from app.models.database import SessionLocal
        from app.services.odds_tracker.snapshot_persistence import persist_snapshot
        session = SessionLocal()
        try:
            persist_snapshot(session, match_id, snapshot)
        finally:
            session.close()
    except Exception as e:
        logger.warning("DB persist failed for snapshot %s: %s", match_id, e)


async def store_odds_snapshot(
    redis_client, match_id: str, odds: dict,
    sport: str = "football",
    sharp_odds: Optional[dict] = None,
    market: str = MARKET_1X2,
) -> dict:
    """Append one odds snapshot to Redis AND persist to PostgreSQL.

    Snapshot shape varies by ``market``:
      - market='1x2' football  → keys home, draw, away
      - market='1x2' tennis    → keys player1, player2
      - market='ou_2.5' etc.   → keys over, under, line

    Returns the snapshot dict that was written so callers (e.g. the
    Telegram alert dispatcher) can act on it without re-reading Redis.
    """
    snapshot: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sport": sport,
        "market": market,
        "bookmaker": odds.get("bookmaker"),
    }

    if market == MARKET_1X2:
        if sport == "tennis":
            snapshot["player1"] = odds.get("player1")
            snapshot["player2"] = odds.get("player2")
        else:  # football
            snapshot["home"] = odds.get("home")
            snapshot["draw"] = odds.get("draw")
            snapshot["away"] = odds.get("away")
    else:
        # Over/Under (and future totals-style markets).
        snapshot["over"] = odds.get("over")
        snapshot["under"] = odds.get("under")
        if odds.get("line") is not None:
            snapshot["line"] = odds.get("line")

    if sharp_odds:
        snapshot["sharp_odds"] = sharp_odds

    await redis_client.rpush(
        odds_history_key(match_id, market), json.dumps(snapshot),
    )
    logger.info("Stored odds snapshot for %s (%s/%s): %s", match_id, sport, market, snapshot)

    # Dual-write to PostgreSQL (non-blocking, best-effort)
    import asyncio
    asyncio.get_event_loop().run_in_executor(
        None, _persist_snapshot_to_db, match_id, snapshot
    )

    return snapshot


async def get_odds_history(
    redis_client,
    match_id: str,
    market: str = MARKET_1X2,
) -> list[dict]:
    """Return full odds history for a match on a specific market, oldest first."""
    raw_entries = await redis_client.lrange(
        odds_history_key(match_id, market), 0, -1,
    )
    return [json.loads(entry) for entry in raw_entries]


async def get_match_meta(redis_client, match_id: str) -> Optional[dict]:
    raw = await redis_client.get(match_meta_key(match_id))
    return json.loads(raw) if raw else None


async def get_all_tracked_ids(redis_client) -> list[str]:
    members = await redis_client.smembers(TRACKED_INDEX_KEY)
    return [m.decode() if isinstance(m, bytes) else m for m in members]


async def is_already_tracked(redis_client, match_id: str) -> bool:
    return await redis_client.sismember(TRACKED_INDEX_KEY, match_id)


def _persist_match_to_db(match_id: str, meta: dict):
    """Write match metadata to PostgreSQL. Runs in a thread — must be sync."""
    try:
        from app.models.database import SessionLocal
        from app.services.odds_tracker.snapshot_persistence import persist_match
        session = SessionLocal()
        try:
            persist_match(session, match_id, meta)
        finally:
            session.close()
    except Exception as e:
        logger.warning("DB persist failed for match %s: %s", match_id, e)


def _update_match_start_time_in_db(match_id: str, start_time: str | None, start_time_raw: str | None):
    """Update start_time in PostgreSQL. Runs in a thread — must be sync."""
    try:
        from app.models.database import SessionLocal
        from app.services.odds_tracker.snapshot_persistence import update_match_start_time
        session = SessionLocal()
        try:
            update_match_start_time(session, match_id, start_time, start_time_raw)
        finally:
            session.close()
    except Exception as e:
        logger.warning("DB start_time update failed for match %s: %s", match_id, e)


async def register_match(redis_client, match_id: str, meta: dict):
    """Persist match metadata to Redis and PostgreSQL, add to tracking index."""
    await redis_client.set(match_meta_key(match_id), json.dumps(meta))
    await redis_client.sadd(TRACKED_INDEX_KEY, match_id)
    logger.info("Registered match %s for tracking: %s", match_id, meta)

    import asyncio
    asyncio.get_event_loop().run_in_executor(
        None, _persist_match_to_db, match_id, meta
    )


def _update_match_status_in_db(match_id: str, status: str):
    """Update match status in PostgreSQL. Runs in a thread — must be sync."""
    try:
        from app.models.database import SessionLocal
        from app.services.odds_tracker.snapshot_persistence import update_match_status
        session = SessionLocal()
        try:
            update_match_status(session, match_id, status)
        finally:
            session.close()
    except Exception as e:
        logger.warning("DB status update failed for match %s: %s", match_id, e)


async def update_match_meta_field(redis_client, match_id: str, field: str, value):
    """Update a single field in the match metadata stored in Redis + DB."""
    raw = await redis_client.get(match_meta_key(match_id))
    if not raw:
        return
    meta = json.loads(raw)
    meta[field] = value
    await redis_client.set(match_meta_key(match_id), json.dumps(meta))
    logger.info("Updated %s for match %s: %s", field, match_id, value)


async def unregister_match(redis_client, match_id: str):
    """Remove match from active tracking index (keep history intact)."""
    await redis_client.srem(TRACKED_INDEX_KEY, match_id)
    # Update status in meta
    raw = await redis_client.get(match_meta_key(match_id))
    if raw:
        meta = json.loads(raw)
        meta["status"] = "completed"
        await redis_client.set(match_meta_key(match_id), json.dumps(meta))
    logger.info("Unregistered match %s — tracking complete.", match_id)

    import asyncio
    asyncio.get_event_loop().run_in_executor(
        None, _update_match_status_in_db, match_id, "completed"
    )
