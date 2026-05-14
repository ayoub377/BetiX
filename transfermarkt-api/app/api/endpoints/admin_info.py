"""Admin dashboard endpoint — surfaces who is on the platform, what is being
tracked, and how much external API spend the trackers are projected to incur.

All routes require role=admin. Designed to be cheap to call (~ a few small
SQL queries + a handful of Redis reads) so it can back a live dashboard
without paging the database.
"""

import datetime
import logging
import os
import uuid
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import require_role
from app.core.config import redis_client
from app.core.quotas import normalize_role
from app.models.database import get_db
from app.models.odds_models import MatchResult, OddsSnapshot, TrackedMatch
from app.models.users import User
from app.services.odds_api.odds_api_client import (
    ODDS_API_DAILY_KEY_PREFIX,
    ODDS_API_TOTAL_KEY,
)
from app.services.odds_tracker.odds_scheduler import scheduler
from app.services.odds_tracker.odds_tracker import get_all_tracked_ids, get_match_meta

logger = logging.getLogger(__name__)

router = APIRouter()


# Daily Odds API calls history shown on the dashboard. 14 days keeps the
# payload small while still letting an admin spot weekly patterns.
DAILY_HISTORY_DAYS = 14


async def _users_section(db: Session) -> dict:
    """Counts by role + recent signups. Cheap: 3 indexed COUNT queries."""
    by_role_rows = (
        db.query(User.role, func.count(User.id))
        .group_by(User.role)
        .all()
    )
    by_role = {role or "normal": count for role, count in by_role_rows}
    total = sum(by_role.values())

    # Anyone whose subscription_status looks active. The webhook handler
    # writes statuses like "active", "on_trial", "past_due", "cancelled" —
    # we treat the first two as paying users.
    active_sub_count = (
        db.query(func.count(User.id))
        .filter(User.subscription_status.in_(["active", "on_trial"]))
        .scalar()
    ) or 0

    now = datetime.datetime.now(datetime.timezone.utc)
    seven_days_ago = now - datetime.timedelta(days=7)
    thirty_days_ago = now - datetime.timedelta(days=30)

    signups_7d = (
        db.query(func.count(User.id))
        .filter(User.created_at >= seven_days_ago)
        .scalar()
    ) or 0
    signups_30d = (
        db.query(func.count(User.id))
        .filter(User.created_at >= thirty_days_ago)
        .scalar()
    ) or 0

    return {
        "total": total,
        "by_role": {
            "normal": by_role.get("normal", 0),
            "premium": by_role.get("premium", 0),
            "admin": by_role.get("admin", 0),
        },
        # ``paying`` is the cost-relevant subset: people we expect to keep
        # consuming Odds API quota. Distinct from role=premium because a
        # cancelled premium subscriber still has role=premium until their
        # period ends.
        "paying": active_sub_count,
        "signups_last_7d": signups_7d,
        "signups_last_30d": signups_30d,
    }


def _seconds_to_daily_calls(poll_interval_seconds: Optional[int]) -> float:
    """Translate a per-match poll cadence to the projected calls/day it adds
    to our Odds API spend. Falls back to the slowest tier when the cadence
    isn't stored on the row (legacy data)."""
    if not poll_interval_seconds or poll_interval_seconds <= 0:
        poll_interval_seconds = 45 * 60  # the "normal" tier fallback
    return 86400.0 / poll_interval_seconds


async def _tracking_section(db: Session) -> dict:
    """Tracker counts and the projected Odds API spend they imply."""
    total = db.query(func.count(TrackedMatch.id)).scalar() or 0

    by_status_rows = (
        db.query(TrackedMatch.status, func.count(TrackedMatch.id))
        .group_by(TrackedMatch.status)
        .all()
    )
    by_status = {status or "unknown": count for status, count in by_status_rows}

    by_sport_rows = (
        db.query(TrackedMatch.sport, func.count(TrackedMatch.id))
        .group_by(TrackedMatch.sport)
        .all()
    )
    by_sport = {sport or "unknown": count for sport, count in by_sport_rows}

    # Active = scheduler currently polling. The DB ``status="tracking"``
    # filter is the canonical signal; the Redis index + scheduler jobs are
    # secondary diagnostics in case the three drift.
    active_rows = (
        db.query(TrackedMatch)
        .filter(TrackedMatch.status == "tracking")
        .all()
    )
    active_count = len(active_rows)

    active_by_sport: Counter[str] = Counter()
    projected_calls_per_day = 0.0
    per_user_active: Counter[str] = Counter()

    for row in active_rows:
        active_by_sport[row.sport or "unknown"] += 1
        projected_calls_per_day += _seconds_to_daily_calls(row.poll_interval_seconds)
        if row.user_id is not None:
            per_user_active[str(row.user_id)] += 1

    # Top-10 active users so we can spot a single account driving cost.
    top_users_active = per_user_active.most_common(10)
    top_users_payload: list[dict] = []
    if top_users_active:
        # ``user_id`` is stored as UUID — the typed in_() clause needs UUID
        # objects (SQLite's UUID adapter rejects raw strings), so convert
        # explicitly. Bad strings are dropped to keep the dashboard resilient.
        uuid_objs: list[uuid.UUID] = []
        for uid, _ in top_users_active:
            try:
                uuid_objs.append(uuid.UUID(uid))
            except (ValueError, AttributeError):
                continue
        rows = (
            db.query(User).filter(User.id.in_(uuid_objs)).all() if uuid_objs else []
        )
        users_by_id = {str(u.id): u for u in rows}
        for uid, active in top_users_active:
            u = users_by_id.get(uid)
            top_users_payload.append({
                "user_id": uid,
                "email": u.email if u else None,
                "role": normalize_role(u.role) if u else "unknown",
                "active_trackers": active,
            })

    # Diagnostic cross-checks. Drift between these three numbers means
    # something needs reconciliation (e.g. a job died but the DB row still
    # claims it's "tracking").
    try:
        redis_index_ids = await get_all_tracked_ids(redis_client)
        redis_index_size = len(redis_index_ids)
    except Exception as e:
        logger.warning("Failed to read Redis tracked_matches_index: %s", e)
        redis_index_size = None

    try:
        scheduler_jobs = [j for j in scheduler.get_jobs() if j.id.startswith("odds_scrape_")]
        scheduler_job_count = len(scheduler_jobs)
    except Exception as e:
        logger.warning("Failed to read scheduler jobs: %s", e)
        scheduler_job_count = None

    snapshot_total = db.query(func.count(OddsSnapshot.id)).scalar() or 0

    pending_results = (
        db.query(func.count(MatchResult.match_id))
        .filter(MatchResult.completed.is_(False))
        .scalar()
    ) or 0

    return {
        "total_matches_ever": total,
        "active_trackers": active_count,
        "by_status": by_status,
        "by_sport": by_sport,
        "active_by_sport": dict(active_by_sport),
        "top_active_users": top_users_payload,
        "redis_index_size": redis_index_size,
        "scheduler_job_count": scheduler_job_count,
        "pending_match_results": pending_results,
        "total_snapshots": snapshot_total,
        # Projected Odds API calls/day driven *just* by active trackers.
        # Each poll fires fetch_sharp_odds once, so this is a close lower
        # bound on tomorrow's spend if no trackers are added or removed.
        "projected_odds_api_calls_per_day": round(projected_calls_per_day, 1),
    }


async def _odds_api_section() -> dict:
    """Lifetime + recent daily Odds API call counts pulled from Redis."""
    configured = bool(os.environ.get("ODDS_API_KEY"))

    total: Optional[int] = None
    calls_today: Optional[int] = None
    daily_history: list[dict] = []

    try:
        total_raw = await redis_client.get(ODDS_API_TOTAL_KEY)
        total = int(total_raw) if total_raw else 0

        today = datetime.date.today()
        for offset in range(DAILY_HISTORY_DAYS):
            day = today - datetime.timedelta(days=offset)
            key = ODDS_API_DAILY_KEY_PREFIX + day.isoformat()
            raw = await redis_client.get(key)
            count = int(raw) if raw else 0
            daily_history.append({"date": day.isoformat(), "calls": count})
            if offset == 0:
                calls_today = count
    except Exception as e:
        logger.warning("Failed to read Odds API usage counters: %s", e)

    return {
        "configured": configured,
        "calls_today": calls_today,
        "calls_total": total,
        "daily_history": daily_history,
    }


async def _redis_section() -> dict:
    """Live Redis state useful for debugging cost spikes."""
    try:
        daily_track_keys = await redis_client.keys("daily_tracks:*")
        daily_track_counters = len(daily_track_keys)
    except Exception as e:
        logger.warning("Failed to read daily_tracks:* keys: %s", e)
        daily_track_counters = None

    return {
        "daily_track_counters_active": daily_track_counters,
    }


@router.get("/info")
async def admin_info(
    _user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """Snapshot of platform state — users, tracking load, and Odds API spend.

    Returns a single JSON document with four top-level sections (``users``,
    ``tracking``, ``odds_api``, ``redis``) plus a ``generated_at`` timestamp.
    Safe to call frequently; all queries are indexed counts.
    """
    users = await _users_section(db)
    tracking = await _tracking_section(db)
    odds_api = await _odds_api_section()
    redis_state = await _redis_section()

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "users": users,
        "tracking": tracking,
        "odds_api": odds_api,
        "redis": redis_state,
    }
