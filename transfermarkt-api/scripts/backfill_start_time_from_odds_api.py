"""One-off backfill: re-fetch commence_time from The Odds API and overwrite
the stored ``start_time`` for every tracked match that has an
``odds_api_event_id``. Updates both PostgreSQL (``tracked_matches``) and
Redis (``tracked_match:<id>``).

Run once after deploying the kickoff-time fix, then delete this script.

Usage (from repo root, scraper-service VM, or wherever DATABASE_URL+REDIS_HOST
+ODDS_API_KEY resolve correctly):

    cd transfermarkt-api
    poetry run python scripts/backfill_start_time_from_odds_api.py
"""
import asyncio
import json
import logging
import os
import sys

# Make `app.*` importable when run from transfermarkt-api/ root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.database import SessionLocal
from app.models.odds_models import TrackedMatch
from app.services.odds_api.odds_api_client import get_event_commence_time
from app.services.odds_tracker.snapshot_persistence import update_match_start_time
from app.settings import settings as app_settings  # noqa: F401  (ensures REDIS_HOST etc. resolved)

import redis.asyncio as aioredis

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_start_time")


async def _update_redis_meta(redis_client, match_id: str, new_start_time: str) -> bool:
    key = f"tracked_match:{match_id}"
    raw = await redis_client.get(key)
    if not raw:
        return False
    meta = json.loads(raw)
    meta["start_time"] = new_start_time
    meta["start_time_source"] = "odds_api"
    await redis_client.set(key, json.dumps(meta))
    return True


async def main():
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        logger.error("ODDS_API_KEY not set — aborting.")
        sys.exit(2)

    redis_host = os.environ.get("REDIS_HOST", "localhost")
    redis_client = aioredis.Redis(host=redis_host, decode_responses=True)

    session = SessionLocal()
    try:
        rows = (
            session.query(TrackedMatch)
            .filter(TrackedMatch.odds_api_event_id.isnot(None))
            .all()
        )
        logger.info("Found %d tracked matches with an Odds API event id.", len(rows))

        updated = 0
        skipped = 0
        unchanged = 0
        for row in rows:
            commence = get_event_commence_time(
                api_key, row.odds_api_sport_key, row.odds_api_event_id
            )
            if not commence:
                skipped += 1
                logger.warning(
                    "No commence_time from Odds API for %s (%s/%s) — leaving as-is.",
                    row.match_id, row.odds_api_sport_key, row.odds_api_event_id,
                )
                continue
            if commence == row.start_time:
                unchanged += 1
                continue
            old = row.start_time
            update_match_start_time(session, row.match_id, commence, None)
            await _update_redis_meta(redis_client, row.match_id, commence)
            updated += 1
            logger.info("Backfilled %s: %s → %s", row.match_id, old, commence)

        logger.info(
            "Backfill complete — updated=%d unchanged=%d skipped_missing_commence=%d",
            updated, unchanged, skipped,
        )
    finally:
        session.close()
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
