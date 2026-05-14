"""Tests for the /admin/info dashboard endpoint.

Exercises the section-builder functions directly against an in-memory
SQLite database and a mocked Redis client, mirroring the style used by
tests/odds/*. Full HTTP routing is covered transitively by FastAPI; what
matters here is the math (projected API spend, signup window cutoffs)
and the shape of the JSON payload.
"""
import asyncio
import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.endpoints.admin_info import (
    _odds_api_section,
    _redis_section,
    _seconds_to_daily_calls,
    _tracking_section,
    _users_section,
    DAILY_HISTORY_DAYS,
)
from app.models.odds_models import Base, TrackedMatch
from app.models.users import User


@pytest.fixture
def db_session():
    """SQLite in-memory DB with both ``users`` and ``tracked_matches`` tables.

    The conftest at tests/conftest.py imports app.models.users so the FK from
    tracked_matches.user_id → users.id resolves against shared Base metadata.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _run(coro):
    """Tiny sync runner so tests can stay synchronous."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _add_user(session, *, role="normal", subscription_status=None, created_days_ago=0, email=None):
    user = User(
        id=uuid.uuid4(),
        firebase_uid=f"uid-{uuid.uuid4().hex[:8]}",
        email=email or f"u-{uuid.uuid4().hex[:6]}@example.com",
        role=role,
        subscription_status=subscription_status,
        created_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=created_days_ago),
    )
    session.add(user)
    session.commit()
    return user


def _add_tracker(session, *, user_id=None, sport="football", status="tracking", poll_interval=600, match_id=None):
    row = TrackedMatch(
        match_id=match_id or f"M{uuid.uuid4().hex[:8].upper()}",
        sport=sport,
        home_team="A",
        away_team="B",
        status=status,
        user_id=user_id,
        poll_interval_seconds=poll_interval,
    )
    session.add(row)
    session.commit()
    return row


# ── _seconds_to_daily_calls ──────────────────────────────────────────

class TestProjectedCallsMath:
    def test_ten_minute_poll_gives_144_per_day(self):
        # 86400 / 600 == 144
        assert _seconds_to_daily_calls(600) == pytest.approx(144.0)

    def test_forty_five_minute_poll_gives_32_per_day(self):
        # 86400 / 2700 == 32
        assert _seconds_to_daily_calls(45 * 60) == pytest.approx(32.0)

    def test_missing_interval_falls_back_to_slowest_tier(self):
        # None should be treated as the 45-minute "normal" cadence so we
        # don't crash on a legacy row and don't over-estimate spend.
        assert _seconds_to_daily_calls(None) == pytest.approx(32.0)

    def test_zero_interval_falls_back_to_slowest_tier(self):
        assert _seconds_to_daily_calls(0) == pytest.approx(32.0)


# ── _users_section ───────────────────────────────────────────────────

class TestUsersSection:
    def test_counts_users_by_role(self, db_session):
        _add_user(db_session, role="normal")
        _add_user(db_session, role="normal")
        _add_user(db_session, role="premium")
        _add_user(db_session, role="admin")

        result = _run(_users_section(db_session))

        assert result["total"] == 4
        assert result["by_role"] == {"normal": 2, "premium": 1, "admin": 1}

    def test_paying_counts_only_active_subscriptions(self, db_session):
        _add_user(db_session, role="premium", subscription_status="active")
        _add_user(db_session, role="premium", subscription_status="on_trial")
        _add_user(db_session, role="premium", subscription_status="cancelled")
        _add_user(db_session, role="normal", subscription_status=None)

        result = _run(_users_section(db_session))

        # Only "active" + "on_trial" count as paying; cancelled subscribers
        # still have role=premium but no longer pay us.
        assert result["paying"] == 2

    def test_signup_windows(self, db_session):
        _add_user(db_session, created_days_ago=1)   # in last 7d AND 30d
        _add_user(db_session, created_days_ago=5)   # in last 7d AND 30d
        _add_user(db_session, created_days_ago=10)  # only in last 30d
        _add_user(db_session, created_days_ago=40)  # in neither

        result = _run(_users_section(db_session))

        assert result["signups_last_7d"] == 2
        assert result["signups_last_30d"] == 3

    def test_empty_db_returns_zeroes(self, db_session):
        result = _run(_users_section(db_session))

        assert result["total"] == 0
        assert result["by_role"] == {"normal": 0, "premium": 0, "admin": 0}
        assert result["paying"] == 0
        assert result["signups_last_7d"] == 0
        assert result["signups_last_30d"] == 0


# ── _tracking_section ────────────────────────────────────────────────

class TestTrackingSection:
    @pytest.fixture(autouse=True)
    def _mock_external_state(self):
        """Stub Redis + scheduler globals so the section function can run
        without a live infrastructure. The shape of the returned values is
        chosen to match what the real helpers would produce.
        """
        with patch("app.api.endpoints.admin_info.get_all_tracked_ids", new=AsyncMock(return_value=[])), \
             patch("app.api.endpoints.admin_info.scheduler") as mock_scheduler:
            mock_scheduler.get_jobs.return_value = []
            yield

    def test_active_count_and_projected_spend(self, db_session):
        user = _add_user(db_session, role="premium")
        # Two active premium-cadence trackers (10 min) and one stopped.
        _add_tracker(db_session, user_id=user.id, poll_interval=600, status="tracking")
        _add_tracker(db_session, user_id=user.id, poll_interval=600, status="tracking")
        _add_tracker(db_session, user_id=user.id, poll_interval=2700, status="completed")

        result = _run(_tracking_section(db_session))

        assert result["total_matches_ever"] == 3
        assert result["active_trackers"] == 2
        # Only active trackers contribute to projected spend: 2 × 144 = 288.
        assert result["projected_odds_api_calls_per_day"] == pytest.approx(288.0)

    def test_breakdown_by_sport(self, db_session):
        _add_tracker(db_session, sport="football", status="tracking")
        _add_tracker(db_session, sport="football", status="completed")
        _add_tracker(db_session, sport="tennis", status="tracking")

        result = _run(_tracking_section(db_session))

        assert result["by_sport"] == {"football": 2, "tennis": 1}
        assert result["active_by_sport"] == {"football": 1, "tennis": 1}

    def test_top_active_users_includes_email(self, db_session):
        heavy = _add_user(db_session, role="premium", email="heavy@example.com")
        light = _add_user(db_session, role="normal", email="light@example.com")
        for _ in range(3):
            _add_tracker(db_session, user_id=heavy.id, status="tracking")
        _add_tracker(db_session, user_id=light.id, status="tracking")

        result = _run(_tracking_section(db_session))

        top = result["top_active_users"]
        assert len(top) == 2
        # Sorted by count descending — heavy user first.
        assert top[0]["email"] == "heavy@example.com"
        assert top[0]["active_trackers"] == 3
        assert top[0]["role"] == "premium"
        assert top[1]["email"] == "light@example.com"
        assert top[1]["active_trackers"] == 1

    def test_legacy_row_without_poll_interval_does_not_crash(self, db_session):
        # Pre-PR2 rows have poll_interval_seconds=None.
        _add_tracker(db_session, poll_interval=None, status="tracking")

        result = _run(_tracking_section(db_session))

        assert result["active_trackers"] == 1
        # Fallback to "normal" cadence (45 min → 32 calls/day).
        assert result["projected_odds_api_calls_per_day"] == pytest.approx(32.0)


# ── _odds_api_section ────────────────────────────────────────────────

class TestOddsApiSection:
    def test_returns_lifetime_and_daily_history(self):
        async def fake_get(key):
            mapping = {
                "odds_api:calls:total": "1284",
                f"odds_api:calls:{datetime.date.today().isoformat()}": "47",
            }
            return mapping.get(key)

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(side_effect=fake_get)

        with patch("app.api.endpoints.admin_info.redis_client", mock_redis), \
             patch.dict("os.environ", {"ODDS_API_KEY": "test-key"}):
            result = _run(_odds_api_section())

        assert result["configured"] is True
        assert result["calls_total"] == 1284
        assert result["calls_today"] == 47
        assert len(result["daily_history"]) == DAILY_HISTORY_DAYS
        # First entry is today.
        assert result["daily_history"][0]["date"] == datetime.date.today().isoformat()
        assert result["daily_history"][0]["calls"] == 47

    def test_missing_api_key_marks_unconfigured(self):
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("app.api.endpoints.admin_info.redis_client", mock_redis), \
             patch.dict("os.environ", {}, clear=True):
            result = _run(_odds_api_section())

        assert result["configured"] is False
        assert result["calls_total"] == 0
        assert result["calls_today"] == 0


# ── _redis_section ───────────────────────────────────────────────────

class TestRedisSection:
    def test_counts_active_daily_track_counters(self):
        mock_redis = MagicMock()
        mock_redis.keys = AsyncMock(return_value=["daily_tracks:u1", "daily_tracks:u2", "daily_tracks:u3"])

        with patch("app.api.endpoints.admin_info.redis_client", mock_redis):
            result = _run(_redis_section())

        assert result["daily_track_counters_active"] == 3

    def test_swallows_redis_errors(self):
        mock_redis = MagicMock()
        mock_redis.keys = AsyncMock(side_effect=RuntimeError("redis down"))

        with patch("app.api.endpoints.admin_info.redis_client", mock_redis):
            result = _run(_redis_section())

        # We surface None rather than raising — the dashboard should still
        # render even if Redis is unreachable.
        assert result["daily_track_counters_active"] is None
