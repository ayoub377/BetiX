"""Tests for primary_odds resolver and history decoration."""
from app.services.odds_tracker.primary_odds import (
    resolve_primary_odds,
    decorate_history,
)


def _football_snapshot(home, draw, away, *, bookmaker="Betclic", pinnacle=None):
    snap = {
        "timestamp": "2026-04-27T12:00:00+00:00",
        "sport": "football",
        "bookmaker": bookmaker,
        "home": home,
        "draw": draw,
        "away": away,
    }
    if pinnacle is not None:
        snap["sharp_odds"] = {"pinnacle": pinnacle}
    return snap


def _tennis_snapshot(p1, p2, *, bookmaker="Betclic", pinnacle=None):
    snap = {
        "timestamp": "2026-04-27T12:00:00+00:00",
        "sport": "tennis",
        "bookmaker": bookmaker,
        "player1": p1,
        "player2": p2,
    }
    if pinnacle is not None:
        snap["sharp_odds"] = {"pinnacle": pinnacle}
    return snap


class TestResolvePrimaryOdds:
    def test_pinnacle_preferred_when_complete(self):
        snap = _football_snapshot(
            2.50, 3.20, 2.80,
            pinnacle={"home": 2.45, "draw": 3.25, "away": 2.85},
        )
        out = resolve_primary_odds(snap)
        assert out["primary_source"] == "pinnacle"
        assert out["primary_odds"] == {"home": 2.45, "draw": 3.25, "away": 2.85}

    def test_falls_back_when_pinnacle_missing(self):
        snap = _football_snapshot(2.50, 3.20, 2.80)
        out = resolve_primary_odds(snap)
        assert out["primary_source"] == "betclic"
        assert out["primary_odds"] == {"home": 2.50, "draw": 3.20, "away": 2.80}

    def test_falls_back_when_pinnacle_partial(self):
        # Missing draw — should fall back to Betclic, not surface a half-formed price.
        snap = _football_snapshot(
            2.50, 3.20, 2.80,
            pinnacle={"home": 2.45, "away": 2.85},
        )
        out = resolve_primary_odds(snap)
        assert out["primary_source"] == "betclic"

    def test_pinnacle_with_invalid_value_falls_back(self):
        snap = _football_snapshot(
            2.50, 3.20, 2.80,
            pinnacle={"home": 1.0, "draw": 3.25, "away": 2.85},  # 1.0 is not a real price
        )
        out = resolve_primary_odds(snap)
        assert out["primary_source"] == "betclic"

    def test_tennis_pinnacle(self):
        snap = _tennis_snapshot(
            1.50, 2.60,
            pinnacle={"player1": 1.48, "player2": 2.65},
        )
        out = resolve_primary_odds(snap)
        assert out["primary_source"] == "pinnacle"
        assert out["primary_odds"] == {"player1": 1.48, "player2": 2.65}

    def test_tennis_falls_back(self):
        snap = _tennis_snapshot(1.50, 2.60)
        out = resolve_primary_odds(snap)
        assert out["primary_source"] == "betclic"
        assert out["primary_odds"] == {"player1": 1.50, "player2": 2.60}

    def test_bookmaker_label_lowercased(self):
        snap = _football_snapshot(2.5, 3.2, 2.8, bookmaker="Bet365")
        out = resolve_primary_odds(snap)
        assert out["primary_source"] == "bet365"

    def test_no_data_returns_none(self):
        snap = {
            "timestamp": "2026-04-27T12:00:00+00:00",
            "sport": "football",
            "bookmaker": "Betclic",
        }
        out = resolve_primary_odds(snap)
        assert out["primary_source"] is None
        assert out["primary_odds"] is None


class TestDecorateHistory:
    def test_first_snapshot_has_no_change(self):
        history = [_football_snapshot(2.5, 3.2, 2.8)]
        out = decorate_history(history)
        assert out[0]["primary_change"] is None
        assert out[0]["primary_change_pct"] is None

    def test_change_computed_on_same_source(self):
        history = [
            _football_snapshot(
                2.50, 3.20, 2.80,
                pinnacle={"home": 2.50, "draw": 3.20, "away": 2.80},
            ),
            _football_snapshot(
                2.40, 3.30, 2.90,
                pinnacle={"home": 2.45, "draw": 3.25, "away": 2.85},
            ),
        ]
        out = decorate_history(history)
        assert out[1]["primary_source"] == "pinnacle"
        assert out[1]["primary_change"] == {
            "home": -0.05,
            "draw": 0.05,
            "away": 0.05,
        }
        # Percentages rounded to 2dp
        assert out[1]["primary_change_pct"]["home"] == round(-0.05 / 2.50 * 100, 2)

    def test_change_null_on_source_flip(self):
        # Pinnacle present, then drops out — comparing Pinnacle to Betclic
        # would be misleading, so primary_change must be null.
        history = [
            _football_snapshot(
                2.50, 3.20, 2.80,
                pinnacle={"home": 2.45, "draw": 3.25, "away": 2.85},
            ),
            _football_snapshot(2.40, 3.30, 2.90),  # no Pinnacle
        ]
        out = decorate_history(history)
        assert out[0]["primary_source"] == "pinnacle"
        assert out[1]["primary_source"] == "betclic"
        assert out[1]["primary_change"] is None
        assert out[1]["primary_change_pct"] is None

    def test_change_only_against_immediate_previous(self):
        # Source flips both directions — change must be null on every flip,
        # never reaching back to a non-adjacent snapshot of the same source.
        history = [
            _football_snapshot(
                2.50, 3.20, 2.80,
                pinnacle={"home": 2.45, "draw": 3.25, "away": 2.85},
            ),
            _football_snapshot(2.40, 3.30, 2.90),  # gap (Betclic-only)
            _football_snapshot(
                2.30, 3.40, 3.00,
                pinnacle={"home": 2.50, "draw": 3.20, "away": 2.80},
            ),
        ]
        out = decorate_history(history)
        assert out[2]["primary_source"] == "pinnacle"
        # Previous snapshot was Betclic — flipping back to Pinnacle nulls change.
        assert out[2]["primary_change"] is None
        assert out[2]["primary_change_pct"] is None

    def test_change_computed_on_consecutive_betclic(self):
        # Two consecutive Betclic-only (no Pinnacle) snapshots → change is computed.
        history = [
            _football_snapshot(2.50, 3.20, 2.80),
            _football_snapshot(2.45, 3.25, 2.85),
        ]
        out = decorate_history(history)
        assert out[1]["primary_source"] == "betclic"
        assert out[1]["primary_change"] == {
            "home": -0.05,
            "draw": 0.05,
            "away": 0.05,
        }
