import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.models.markets import DEFAULT_MARKETS, MARKET_1X2, is_supported
from app.services.odds_tracker.odds_tracker import (
    store_odds_snapshot, get_match_meta,
    unregister_match, update_match_meta_field, TRACKED_INDEX_KEY,
    _update_match_start_time_in_db,
)
from app.core.config import SCRAPE_INTERVAL_SECONDS, STOP_BEFORE_KICKOFF_SECONDS

logger = logging.getLogger(__name__)

# Single shared scheduler instance — imported by the FastAPI app
scheduler = AsyncIOScheduler()

io_executor = ThreadPoolExecutor(max_workers=50)


def _fetch_sharp_odds_sync(api_key, sport_key, event_id, home_team, away_team):
    """Fetch sharp bookmaker odds (sync, runs in thread pool)."""
    try:
        from app.services.odds_api.odds_api_client import fetch_sharp_odds
        return fetch_sharp_odds(api_key, sport_key, event_id, home_team, away_team)
    except Exception as e:
        logger.warning("Sharp odds fetch failed: %s", e)
        return {}


def make_scrape_job(match_id: str, scraper, redis_client, sport: str = "football"):
    """
    Returns an async function used as the APScheduler job.
    Captures match_id, scraper, redis_client and sport in closure.
    """

    async def scrape_job():
        logger.info("Running scheduled odds scrape for match %s (%s)", match_id, sport)

        meta = await get_match_meta(redis_client, match_id)

        # ── Refresh start time ──────────────────────────────────────
        # Tennis matches (and some football) can have their start time
        # pushed back (e.g. previous match still in progress).  We
        # re-fetch the start time on every cycle so the tracker
        # doesn't stop too early based on a stale timestamp.
        #
        # Source precedence:
        #   1. Odds API commence_time (when the match has been mapped) —
        #      authoritative UTC ISO from a real API; not affected by
        #      FlashScore's IP-geolocated rendering.
        #   2. FlashScore re-scrape — fallback for matches not on Odds API.
        try:
            loop_st = asyncio.get_event_loop()
            fresh_start = None
            fresh_raw = None
            api_key = os.environ.get("ODDS_API_KEY")
            event_id = meta.get("odds_api_event_id") if meta else None
            sport_key_meta = meta.get("odds_api_sport_key") if meta else None

            if api_key and event_id and sport_key_meta:
                from app.services.odds_api.odds_api_client import get_event_commence_time
                fresh_start = await loop_st.run_in_executor(
                    io_executor, get_event_commence_time,
                    api_key, sport_key_meta, event_id,
                )
            else:
                fresh_info = await loop_st.run_in_executor(
                    io_executor, scraper.get_match_info, match_id
                )
                fresh_start = fresh_info.get("start_time") if fresh_info else None
                fresh_raw = fresh_info.get("start_time_raw") if fresh_info else None

            if fresh_start and meta:
                old_start = meta.get("start_time")
                if fresh_start != old_start:
                    logger.info(
                        "Match %s start time changed: %s → %s",
                        match_id, old_start, fresh_start,
                    )
                    await update_match_meta_field(redis_client, match_id, "start_time", fresh_start)
                    if fresh_raw is not None:
                        await update_match_meta_field(redis_client, match_id, "start_time_raw", fresh_raw)
                    meta["start_time"] = fresh_start
                    # Keep PostgreSQL in sync with Redis — persist_match()
                    # is insert-only, so without this the DB row stays stale.
                    asyncio.get_event_loop().run_in_executor(
                        None, _update_match_start_time_in_db,
                        match_id, fresh_start, fresh_raw,
                    )
        except Exception as e:
            logger.warning("Failed to refresh start time for %s: %s", match_id, e)

        # ── Check if match is about to start ────────────────────────
        if meta:
            start_time_str = meta.get("start_time")
            if start_time_str:
                start_time = datetime.fromisoformat(start_time_str)
                time_until_start = start_time - datetime.now(timezone.utc)
                if time_until_start <= timedelta(seconds=STOP_BEFORE_KICKOFF_SECONDS):
                    logger.info("Match %s starts in %s — stopping tracker.", match_id, time_until_start)
                    await unregister_match(redis_client, match_id)
                    scheduler.remove_job(job_id(match_id))

                    # Hand off to the post-match result poller. First run is
                    # delayed to roughly the end of the match so we don't burn
                    # API quota during play.
                    try:
                        from app.services.odds_tracker.result_scheduler import (
                            schedule_result_polling, RESULT_FIRST_DELAY_SECONDS,
                        )
                        first_run = start_time + timedelta(seconds=RESULT_FIRST_DELAY_SECONDS)
                        if first_run < datetime.now(timezone.utc):
                            first_run = datetime.now(timezone.utc)
                        schedule_result_polling(
                            match_id,
                            sport=meta.get("sport", "football"),
                            odds_api_event_id=meta.get("odds_api_event_id"),
                            first_run_at=first_run,
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to schedule result polling for %s: %s",
                            match_id, e,
                        )
                    return

        # ── Scrape each configured market ───────────────────────────
        # Tennis stays on 1X2 only — non-1X2 markets are football-specific
        # for now (BTTS / OU / etc.). Football honours whatever the user
        # configured at /track time, defaulting to 1X2 only for legacy
        # rows that pre-date the markets column.
        configured = meta.get("markets") if meta else None
        if sport == "tennis":
            markets_to_scrape = [MARKET_1X2]
        elif configured:
            markets_to_scrape = [m for m in configured if is_supported(m)]
            if not markets_to_scrape:
                markets_to_scrape = list(DEFAULT_MARKETS)
        else:
            markets_to_scrape = list(DEFAULT_MARKETS)

        loop = asyncio.get_event_loop()
        api_key = os.environ.get("ODDS_API_KEY")

        for market in markets_to_scrape:
            try:
                if sport == "tennis" or market == MARKET_1X2:
                    # Existing path — keep using the legacy method name
                    # so tennis-only deployments don't need to ship the
                    # new dispatcher method.
                    odds = await loop.run_in_executor(
                        io_executor, scraper.get_odds_by_match_id, match_id,
                    )
                else:
                    # Football, non-1X2 — go through the market dispatcher.
                    odds = await loop.run_in_executor(
                        io_executor, scraper.get_odds_by_market, match_id, market,
                    )

                # Per-market validity check
                if sport == "tennis":
                    has_valid = odds.get("player1") is not None
                elif market == MARKET_1X2:
                    has_valid = odds.get("home") is not None
                else:
                    has_valid = odds.get("over") is not None

                if not has_valid:
                    logger.warning(
                        "No valid odds returned for match %s (%s/%s)",
                        match_id, sport, market,
                    )
                    continue

                # Sharp odds (Odds API) only cover 1X2 for now. When we
                # wire totals/btts to the Odds API we can extend this — for
                # now keep them at None on non-1X2 snapshots so the chart
                # doesn't draw a meaningless sharp series.
                sharp_odds = {}
                if api_key and meta and market == MARKET_1X2:
                    event_id = meta.get("odds_api_event_id")
                    sport_key = meta.get("odds_api_sport_key")
                    if event_id and sport_key:
                        sharp_odds = await loop.run_in_executor(
                            io_executor, _fetch_sharp_odds_sync,
                            api_key, sport_key, event_id,
                            meta.get("home_team", ""), meta.get("away_team", ""),
                        )

                snapshot = await store_odds_snapshot(
                    redis_client, match_id, odds,
                    sport=sport,
                    sharp_odds=sharp_odds or None,
                    market=market,
                )

                # Telegram alert dispatch — best-effort, per market.
                try:
                    from app.services.telegram.alert_dispatcher import maybe_dispatch_alert
                    if meta:
                        await maybe_dispatch_alert(
                            redis_client=redis_client,
                            match_id=match_id,
                            new_snapshot=snapshot,
                            match_meta=meta,
                            sport=sport,
                            market=market,
                        )
                except Exception as e:
                    logger.warning(
                        "Telegram alert dispatch failed for %s (market=%s): %s",
                        match_id, market, e,
                    )
            except Exception as e:
                # A single bad market shouldn't kill the rest of the tick.
                logger.error(
                    "Scrape job failed for match %s market %s: %s",
                    match_id, market, e, exc_info=True,
                )

    return scrape_job


def job_id(match_id: str) -> str:
    return f"odds_scrape_{match_id}"


def start_tracking_job(
    match_id: str,
    scraper,
    redis_client,
    initial_delay: float = 0,
    sport: str = "football",
    poll_interval_seconds: int | None = None,
):
    """
    Schedules a job.
    initial_delay: seconds to wait before the very first execution (useful for restarts).
    sport: the sport type for this match (determines odds key names).
    poll_interval_seconds: how often to refresh odds. Falls back to the global
      ``SCRAPE_INTERVAL_SECONDS`` for legacy callers / matches without a per-row
      cadence (PR2 sets this from the user's tier; before PR2 it was a constant).
    """
    interval = poll_interval_seconds if poll_interval_seconds and poll_interval_seconds > 0 else SCRAPE_INTERVAL_SECONDS
    run_time = datetime.now(timezone.utc) + timedelta(seconds=initial_delay)

    scheduler.add_job(
        make_scrape_job(match_id, scraper, redis_client, sport=sport),
        trigger=IntervalTrigger(seconds=interval),
        id=job_id(match_id),
        replace_existing=True,
        next_run_time=run_time,
    )
    logger.info(
        "Match %s (%s) scheduled (interval=%ds, start delay=%.1fs)",
        match_id, sport, interval, initial_delay,
    )


def stop_tracking_job(match_id: str):
    jid = job_id(match_id)
    if scheduler.get_job(jid):
        scheduler.remove_job(jid)
        logger.info("Removed tracking job for match %s.", match_id)
