"""Tests for match_result persistence + Odds API scores client."""
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.odds_models import Base, MatchResult
from app.services.odds_tracker.snapshot_persistence import (
    upsert_match_result,
    mark_result_completed,
    record_poll_attempt,
    mark_result_timeout,
    get_match_result_from_db,
    get_pending_result_match_ids,
)
from app.services.odds_api.odds_api_client import fetch_event_scores


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ── Persistence ─────────────────────────────────────────────────

class TestUpsertMatchResult:
    def test_creates_pending_row(self, db_session):
        upsert_match_result(db_session, "ABC12345", sport="football")
        row = db_session.query(MatchResult).filter_by(match_id="ABC12345").first()
        assert row is not None
        assert row.completed is False
        assert row.poll_attempts == 0

    def test_idempotent(self, db_session):
        upsert_match_result(db_session, "ABC12345", sport="football")
        upsert_match_result(db_session, "ABC12345", sport="football")
        rows = db_session.query(MatchResult).filter_by(match_id="ABC12345").all()
        assert len(rows) == 1


class TestMarkResultCompleted:
    def test_writes_scores_and_outcome_home(self, db_session):
        upsert_match_result(db_session, "ABC12345", sport="football")
        mark_result_completed(
            db_session, "ABC12345", "football",
            home_score=2, away_score=1, fetched_at="2026-04-27T15:00:00+00:00",
        )
        row = db_session.query(MatchResult).filter_by(match_id="ABC12345").first()
        assert row.completed is True
        assert row.home_score == 2
        assert row.away_score == 1
        assert row.outcome == "home"
        assert row.result_source == "odds_api"

    def test_outcome_draw(self, db_session):
        upsert_match_result(db_session, "ABC", sport="football")
        mark_result_completed(db_session, "ABC", "football", 1, 1, "2026-04-27T15:00:00+00:00")
        assert get_match_result_from_db(db_session, "ABC")["outcome"] == "draw"

    def test_outcome_away(self, db_session):
        upsert_match_result(db_session, "ABC", sport="football")
        mark_result_completed(db_session, "ABC", "football", 0, 3, "2026-04-27T15:00:00+00:00")
        assert get_match_result_from_db(db_session, "ABC")["outcome"] == "away"

    def test_tennis_outcome_p1_wins(self, db_session):
        upsert_match_result(db_session, "T1", sport="tennis")
        mark_result_completed(db_session, "T1", "tennis", 2, 1, "2026-04-27T15:00:00+00:00")
        assert get_match_result_from_db(db_session, "T1")["outcome"] == "p1"

    def test_tennis_outcome_p2_wins(self, db_session):
        upsert_match_result(db_session, "T2", sport="tennis")
        mark_result_completed(db_session, "T2", "tennis", 0, 2, "2026-04-27T15:00:00+00:00")
        assert get_match_result_from_db(db_session, "T2")["outcome"] == "p2"

    def test_creates_row_if_missing(self, db_session):
        # Backfill case: result row didn't exist yet.
        mark_result_completed(
            db_session, "NEW1", "football",
            home_score=3, away_score=0, fetched_at="2026-04-27T15:00:00+00:00",
        )
        result = get_match_result_from_db(db_session, "NEW1")
        assert result["completed"] is True
        assert result["outcome"] == "home"


class TestPollTracking:
    def test_record_poll_attempt_increments(self, db_session):
        upsert_match_result(db_session, "ABC", sport="football")
        n1 = record_poll_attempt(db_session, "ABC", "2026-04-27T15:00:00+00:00")
        n2 = record_poll_attempt(db_session, "ABC", "2026-04-27T15:10:00+00:00")
        assert (n1, n2) == (1, 2)

    def test_mark_timeout(self, db_session):
        upsert_match_result(db_session, "ABC", sport="football")
        record_poll_attempt(db_session, "ABC", "2026-04-27T15:00:00+00:00")
        mark_result_timeout(db_session, "ABC", "2026-04-27T18:00:00+00:00")
        row = get_match_result_from_db(db_session, "ABC")
        assert row["result_source"] == "timeout"
        assert row["completed"] is False

    def test_pending_result_ids(self, db_session):
        upsert_match_result(db_session, "PEND1", sport="football")
        upsert_match_result(db_session, "PEND2", sport="football")
        upsert_match_result(db_session, "DONE1", sport="football")
        mark_result_completed(db_session, "DONE1", "football", 1, 0, "2026-04-27T15:00:00+00:00")

        pending = get_pending_result_match_ids(db_session)
        assert set(pending) == {"PEND1", "PEND2"}


# ── fetch_event_scores ──────────────────────────────────────────

SAMPLE_SCORES_COMPLETED = [
    {
        "id": "event_001",
        "sport_key": "soccer_epl",
        "home_team": "Manchester United",
        "away_team": "Liverpool",
        "completed": True,
        "scores": [
            {"name": "Manchester United", "score": "2"},
            {"name": "Liverpool", "score": "1"},
        ],
    },
]

SAMPLE_SCORES_LIVE = [
    {
        "id": "event_001",
        "home_team": "Manchester United",
        "away_team": "Liverpool",
        "completed": False,
        "scores": [
            {"name": "Manchester United", "score": "1"},
            {"name": "Liverpool", "score": "0"},
        ],
    },
]


class TestFetchEventScores:
    def test_completed_match_parses_scores(self):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = SAMPLE_SCORES_COMPLETED
        with patch("app.services.odds_api.odds_api_client.httpx.get", return_value=mock_resp):
            result = fetch_event_scores(
                "fake-key", "soccer_epl", "event_001",
                "Manchester United", "Liverpool",
            )
        assert result == {"completed": True, "home_score": 2, "away_score": 1}

    def test_live_match_returns_partial(self):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = SAMPLE_SCORES_LIVE
        with patch("app.services.odds_api.odds_api_client.httpx.get", return_value=mock_resp):
            result = fetch_event_scores(
                "fake-key", "soccer_epl", "event_001",
                "Manchester United", "Liverpool",
            )
        assert result == {"completed": False, "home_score": 1, "away_score": 0}

    def test_event_not_found_returns_none(self):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = []
        with patch("app.services.odds_api.odds_api_client.httpx.get", return_value=mock_resp):
            result = fetch_event_scores(
                "fake-key", "soccer_epl", "event_999", "X", "Y",
            )
        assert result is None

    def test_http_error_returns_none(self):
        mock_resp = MagicMock(status_code=429)
        with patch("app.services.odds_api.odds_api_client.httpx.get", return_value=mock_resp):
            result = fetch_event_scores(
                "fake-key", "soccer_epl", "event_001", "X", "Y",
            )
        assert result is None

    def test_null_score_string_skipped(self):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = [{
            "id": "event_001",
            "home_team": "Home",
            "away_team": "Away",
            "completed": False,
            "scores": [
                {"name": "Home", "score": ""},
                {"name": "Away", "score": "0"},
            ],
        }]
        with patch("app.services.odds_api.odds_api_client.httpx.get", return_value=mock_resp):
            result = fetch_event_scores(
                "fake-key", "soccer_epl", "event_001", "Home", "Away",
            )
        assert result["home_score"] is None
        assert result["away_score"] == 0
