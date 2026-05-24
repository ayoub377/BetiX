"""End-to-end pipeline test for the Telegram alert flow.

This is the test you want when you suspect "the 20% drop alert isn't
working in production." It exercises the real production code path:

    make_scrape_job() → scraper.get_odds_by_match_id()
                     → store_odds_snapshot() (writes to Redis)
                     → maybe_dispatch_alert()
                         → compute_breaches()
                         → format_alert_message()
                         → bot_client.send_message()

All external boundaries are mocked so the test is cheap and deterministic:

  - Redis      → ``FakeAsyncRedis`` (in-memory, async, just the ops we use)
  - Postgres   → ``_load_user_prefs`` is patched to return a known stub;
                 the executor-side DB writers (``_persist_*``) are patched
                 to no-ops because we don't observe DB state here.
  - Scraper    → ``MagicMock`` whose ``get_odds_by_match_id`` returns the
                 next entry in a hand-crafted odds sequence on each tick.
  - Telegram   → ``bot_client.send_message`` is replaced by an async stub
                 that appends every call onto ``captured_messages``.
  - Odds API   → ``ODDS_API_KEY`` is cleared so the start-time refresh
                 and sharp-odds paths short-circuit. Snapshot ``sharp_odds``
                 is never populated, which is fine — the alert dispatcher
                 doesn't depend on it.

Reading these tests is the fastest way to understand the alert engine:
each one declares a starting state, fires N scheduler ticks via the real
``make_scrape_job`` factory, and asserts exactly when (and what) the bot
client was called with.
"""
from __future__ import annotations

import asyncio
import datetime as _datetime
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.services.odds_tracker.odds_scheduler import make_scrape_job
from app.services.odds_tracker.odds_tracker import (
    TRACKED_INDEX_KEY,
    match_meta_key,
)
from app.services.telegram.alert_dispatcher import _UserAlertPrefs


# ────────────────────────────────────────────────────────────────────
# Deterministic clock
# ────────────────────────────────────────────────────────────────────
#
# ``store_odds_snapshot`` stamps every snapshot with ``datetime.now()``,
# and the dispatcher uses the timestamp string to detect "this is the
# very first scrape" (opening == new). On Windows, ``datetime.now()``
# has ~15ms resolution — two back-to-back ``await job()`` calls can
# land in the same microsecond and the early-return fires.
#
# Real wall-clock sleeps are flaky and slow. Instead we replace the
# ``datetime`` class inside the snapshot module with a thin wrapper that
# advances by 1 second on every ``now()`` call. The rest of the
# datetime surface (fromisoformat, timezone.utc, timedelta) is
# delegated unchanged so the scheduler's "stop before kickoff" arithmetic
# still works.


class _MonotonicDatetime:
    """``datetime`` look-alike whose ``now()`` advances 1s per call.

    Replaces ``app.services.odds_tracker.odds_tracker.datetime`` for the
    duration of a test so every snapshot gets a distinct timestamp.
    """

    _counter = 0
    # Start in the past so timestamps don't accidentally collide with
    # FUTURE_START_TIME (year 2099) and trip the stop-before-kickoff branch.
    _base = _datetime.datetime(2026, 5, 1, 12, 0, 0, tzinfo=_datetime.timezone.utc)

    @classmethod
    def reset(cls) -> None:
        cls._counter = 0

    @classmethod
    def now(cls, tz=None):
        cls._counter += 1
        return cls._base + _datetime.timedelta(seconds=cls._counter)

    # Pass-throughs so any other usage of `datetime.<x>` still works.
    @staticmethod
    def fromisoformat(s):
        return _datetime.datetime.fromisoformat(s)

    @staticmethod
    def utcnow():
        # Not used by the production code under test, but defined defensively.
        return _MonotonicDatetime.now(_datetime.timezone.utc)


# ────────────────────────────────────────────────────────────────────
# In-memory async Redis stub
# ────────────────────────────────────────────────────────────────────

class FakeAsyncRedis:
    """Minimal async Redis double covering the surface this pipeline uses.

    Deliberately implements ONLY the methods exercised below. Adding more
    is cheap, but keeping the surface narrow means a future production
    change that touches a new Redis method will fail loudly here — which
    is exactly the signal we want from an integration test.
    """

    def __init__(self):
        self._kv: dict[str, str] = {}
        self._sets: dict[str, set[str]] = {}
        self._lists: dict[str, list[str]] = {}

    # --- string ops (used by match meta) -----------------------------
    async def get(self, key: str):
        return self._kv.get(key)

    async def set(self, key: str, value, ex: int | None = None):
        # ``ex`` (TTL) is accepted for API compatibility but ignored —
        # the alert dispatcher doesn't depend on expiry for correctness.
        self._kv[key] = value
        return True

    async def delete(self, key: str):
        self._kv.pop(key, None)
        self._sets.pop(key, None)
        self._lists.pop(key, None)
        return 1

    # --- set ops (tracked-matches index + dedupe set) ----------------
    async def sadd(self, key: str, *members):
        s = self._sets.setdefault(key, set())
        before = len(s)
        s.update(map(str, members))
        return len(s) - before

    async def srem(self, key: str, *members):
        s = self._sets.get(key, set())
        before = len(s)
        for m in members:
            s.discard(str(m))
        return before - len(s)

    async def sismember(self, key: str, member) -> bool:
        return str(member) in self._sets.get(key, set())

    async def smembers(self, key: str) -> set[str]:
        return set(self._sets.get(key, set()))

    # --- list ops (odds history) -------------------------------------
    async def rpush(self, key: str, *values):
        lst = self._lists.setdefault(key, [])
        lst.extend(values)
        return len(lst)

    async def lindex(self, key: str, index: int):
        lst = self._lists.get(key, [])
        if not lst:
            return None
        try:
            return lst[index]
        except IndexError:
            return None

    async def lrange(self, key: str, start: int, end: int):
        lst = self._lists.get(key, [])
        # Redis semantics: end is inclusive; -1 means last.
        if end == -1:
            return list(lst[start:])
        return list(lst[start:end + 1])

    # --- TTL no-op (used by _mark_alerted) ---------------------------
    async def expire(self, key: str, seconds: int) -> bool:
        # Behaviourally a no-op in the test — the alert flow doesn't
        # need real expiry to validate.
        return key in self._kv or key in self._sets or key in self._lists


# ────────────────────────────────────────────────────────────────────
# Shared fixtures
# ────────────────────────────────────────────────────────────────────

MATCH_ID = "TEST_MATCH_1"
USER_ID = "11111111-1111-1111-1111-111111111111"
CHAT_ID = "555000111"

# Far enough in the future that the "stop before kickoff" branch
# in the scrape job never triggers — kickoff is more than 5 minutes
# from now in 2099.
FUTURE_START_TIME = "2099-01-01T00:00:00+00:00"


def _meta(*, sport: str = "football") -> dict:
    return {
        "match_id": MATCH_ID,
        "sport": sport,
        "home_team": "Real Madrid",
        "away_team": "Barcelona",
        "start_time": FUTURE_START_TIME,
        "status": "tracking",
        "user_id": USER_ID,
        # No odds_api_event_id → the scheduler skips Odds API paths
        # and uses the (mocked) scraper for everything.
    }


def _make_scraper(odds_sequence: list[dict]):
    """Build a scraper mock that returns ``odds_sequence[i]`` on call ``i``.

    ``get_match_info`` returns ``None`` start times so the scheduler skips
    the start-time refresh branch — keeps the test focused on the alert
    pipeline rather than fixture-juggling. The pre-set meta start_time
    is what gates the "stop before kickoff" check.
    """
    scraper = MagicMock()
    scraper.get_match_info.return_value = {
        "start_time": None,
        "start_time_raw": None,
    }
    scraper.get_odds_by_match_id.side_effect = list(odds_sequence)
    return scraper


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def fake_redis():
    return FakeAsyncRedis()


@pytest.fixture
def captured_messages():
    """A list that ``bot_client.send_message`` appends to, via the patch
    inside ``patch_pipeline``.
    """
    return []


@pytest.fixture
def patch_pipeline(captured_messages):
    """Single context that patches every external boundary the scrape
    pipeline touches: bot send, user-prefs lookup, DB writers, and
    clears ODDS_API_KEY so the Odds API code path stays asleep.

    Yields a small object exposing ``set_prefs`` so individual tests can
    tune the user's threshold / enabled flag without rewiring all the
    patches.
    """
    state = {"prefs": _UserAlertPrefs(chat_id=CHAT_ID, threshold_pct=5.0, enabled=True)}

    async def fake_send(chat_id, body, **_kw):
        captured_messages.append({"chat_id": chat_id, "body": body})
        return True

    def fake_load_prefs(_user_id):
        return state["prefs"]

    _MonotonicDatetime.reset()

    with patch(
        "app.services.telegram.alert_dispatcher.bot_client.send_message",
        new=fake_send,
    ), patch(
        "app.services.telegram.alert_dispatcher._load_user_prefs",
        side_effect=fake_load_prefs,
    ), patch(
        "app.services.odds_tracker.odds_tracker._persist_snapshot_to_db",
        new=lambda *a, **k: None,
    ), patch(
        "app.services.odds_tracker.odds_tracker._persist_match_to_db",
        new=lambda *a, **k: None,
    ), patch(
        # Force every snapshot to get a distinct timestamp — see
        # _MonotonicDatetime docstring above for why wall-clock won't work.
        "app.services.odds_tracker.odds_tracker.datetime",
        new=_MonotonicDatetime,
    ), patch.dict(os.environ, {}, clear=True):
        # Helper namespace returned so tests can adjust mid-flight.
        class _Ctx:
            def set_prefs(self, **kw):
                current = state["prefs"]
                state["prefs"] = _UserAlertPrefs(
                    chat_id=kw.get("chat_id", current.chat_id),
                    threshold_pct=kw.get("threshold_pct", current.threshold_pct),
                    enabled=kw.get("enabled", current.enabled),
                )

        yield _Ctx()


async def _seed_meta(redis: FakeAsyncRedis, meta: dict):
    """Bypass register_match's DB-write executor task — go straight to Redis."""
    await redis.set(match_meta_key(MATCH_ID), json.dumps(meta))
    await redis.sadd(TRACKED_INDEX_KEY, MATCH_ID)


async def _drive_ticks(scraper, redis: FakeAsyncRedis, n: int, sport: str = "football"):
    """Build the real scrape job and invoke it ``n`` times.

    Each call simulates one APScheduler tick. The ``_MonotonicDatetime``
    patch in ``patch_pipeline`` ensures every snapshot gets a distinct
    timestamp regardless of how fast the ticks run, so the dispatcher
    never mistakes a follow-up tick for the very first one.
    """
    job = make_scrape_job(MATCH_ID, scraper, redis, sport=sport)
    for _ in range(n):
        await job()


# ────────────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────────────

class TestPipelineFiresOnBreach:
    def test_20pct_drop_produces_one_alert(self, fake_redis, patch_pipeline, captured_messages):
        """The canonical case: opening 2.00 → 1.60 = -20% on home, fires
        one DM whose body cites the 2.00 → 1.60 transition.
        """
        scraper = _make_scraper([
            {"home": 2.00, "draw": 3.40, "away": 3.80},  # opening tick
            {"home": 1.60, "draw": 3.40, "away": 3.80},  # -20% on home
        ])

        async def scenario():
            await _seed_meta(fake_redis, _meta())
            await _drive_ticks(scraper, fake_redis, n=2)

        _run(scenario())

        assert len(captured_messages) == 1, (
            f"expected exactly one alert, got {len(captured_messages)}: {captured_messages}"
        )
        msg = captured_messages[0]
        assert msg["chat_id"] == CHAT_ID
        body = msg["body"]
        # Body should carry both ends of the move, the home label, and a
        # down arrow. We intentionally don't pin the exact pct formatting
        # so a small dispatcher tweak (e.g. 1 decimal vs 2) doesn't break
        # this — but the *numbers* matter and must be there.
        assert "2.00" in body
        assert "1.60" in body
        assert "Home" in body
        assert "▼" in body
        assert "Real Madrid vs Barcelona" in body

    def test_multiple_outcome_breaches_in_one_tick(self, fake_redis, patch_pipeline, captured_messages):
        """One snapshot with two outcomes past the threshold sends one
        message that lists both moves. Important: a real match commonly
        moves the favourite *and* the underdog together.
        """
        scraper = _make_scraper([
            {"home": 2.00, "draw": 3.00, "away": 4.00},
            {"home": 1.50, "draw": 3.00, "away": 4.80},  # -25% home, +20% away
        ])

        async def scenario():
            await _seed_meta(fake_redis, _meta())
            await _drive_ticks(scraper, fake_redis, n=2)

        _run(scenario())

        assert len(captured_messages) == 1
        body = captured_messages[0]["body"]
        # Both moves must appear in the single combined alert.
        assert "1.50" in body and "4.80" in body
        assert "▼" in body and "▲" in body


class TestPipelineRespectsThreshold:
    def test_below_threshold_no_alert(self, fake_redis, patch_pipeline, captured_messages):
        """A 4% move with a 5% threshold must NOT alert. This is the test
        that catches a regression where someone accidentally changes the
        breach inequality from ``>=`` to ``>`` (or vice versa) on the
        wrong side of the threshold.
        """
        scraper = _make_scraper([
            {"home": 2.00, "draw": 3.40, "away": 3.80},
            {"home": 1.92, "draw": 3.40, "away": 3.80},  # -4% on home, under 5%
        ])

        async def scenario():
            await _seed_meta(fake_redis, _meta())
            await _drive_ticks(scraper, fake_redis, n=2)

        _run(scenario())

        assert captured_messages == [], (
            f"expected no alert, got: {captured_messages}"
        )


class TestPipelineDedupe:
    def test_three_ticks_same_direction_emits_one_alert(self, fake_redis, patch_pipeline, captured_messages):
        """A line that keeps drifting in the same direction must not spam
        the user. Once we've alerted on (home, down) in this match, the
        next ``home_down`` breach should be suppressed by the dedupe set.
        """
        scraper = _make_scraper([
            {"home": 2.00, "draw": 3.40, "away": 3.80},  # opening
            {"home": 1.60, "draw": 3.40, "away": 3.80},  # -20% — fires
            {"home": 1.40, "draw": 3.40, "away": 3.80},  # -30% — dedupe suppresses
        ])

        async def scenario():
            await _seed_meta(fake_redis, _meta())
            await _drive_ticks(scraper, fake_redis, n=3)

        _run(scenario())

        assert len(captured_messages) == 1


class TestPipelineHonoursUserPrefs:
    def test_disabled_user_gets_nothing(self, fake_redis, patch_pipeline, captured_messages):
        """A user with ``telegram_alerts_enabled=False`` must not receive
        anything, even if the breach is huge. This is the production
        check that prevents a user who disabled alerts from re-receiving
        them after a restart.
        """
        patch_pipeline.set_prefs(enabled=False)

        scraper = _make_scraper([
            {"home": 2.00, "draw": 3.40, "away": 3.80},
            {"home": 1.00, "draw": 3.40, "away": 3.80},  # -50%, huge
        ])

        async def scenario():
            await _seed_meta(fake_redis, _meta())
            await _drive_ticks(scraper, fake_redis, n=2)

        _run(scenario())

        assert captured_messages == []

    def test_threshold_raised_above_move_blocks_alert(self, fake_redis, patch_pipeline, captured_messages):
        """If the user sets a 25% threshold, a 20% move shouldn't fire."""
        patch_pipeline.set_prefs(threshold_pct=25.0)

        scraper = _make_scraper([
            {"home": 2.00, "draw": 3.40, "away": 3.80},
            {"home": 1.60, "draw": 3.40, "away": 3.80},  # -20%, below 25%
        ])

        async def scenario():
            await _seed_meta(fake_redis, _meta())
            await _drive_ticks(scraper, fake_redis, n=2)

        _run(scenario())

        assert captured_messages == []
