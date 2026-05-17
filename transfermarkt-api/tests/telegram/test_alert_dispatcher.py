"""Unit tests for the pure parts of the Telegram alert dispatcher.

I/O paths (Redis, Postgres, Telegram API) are tested separately with mocks;
this file only covers ``compute_breaches`` and ``format_alert_message`` so
the threshold arithmetic stays well-defined as we tune it.
"""
from app.services.telegram.alert_dispatcher import (
    MovementBreach,
    compute_breaches,
    format_alert_message,
)


# ────────────────────────────────────────────────────────────────────
# compute_breaches — football
# ────────────────────────────────────────────────────────────────────

def test_no_breach_when_under_threshold():
    opening = {"home": 2.00, "draw": 3.40, "away": 3.80}
    current = {"home": 2.05, "draw": 3.40, "away": 3.80}  # +2.5% on home
    assert compute_breaches(opening, current, "football", threshold_pct=5.0) == []


def test_breach_up_on_home():
    opening = {"home": 2.00, "draw": 3.40, "away": 3.80}
    current = {"home": 2.20, "draw": 3.40, "away": 3.80}  # +10% home
    breaches = compute_breaches(opening, current, "football", threshold_pct=5.0)
    assert len(breaches) == 1
    b = breaches[0]
    assert b.market == "home"
    assert b.direction == "up"
    assert b.opening_odds == 2.00
    assert b.current_odds == 2.20
    assert b.abs_pct_move == 10.0
    assert b.dedupe_key == "home_up"


def test_breach_down_on_away():
    opening = {"home": 2.00, "draw": 3.40, "away": 4.00}
    current = {"home": 2.00, "draw": 3.40, "away": 3.20}  # -20% away
    breaches = compute_breaches(opening, current, "football", threshold_pct=5.0)
    assert len(breaches) == 1
    assert breaches[0].market == "away"
    assert breaches[0].direction == "down"
    assert breaches[0].abs_pct_move == 20.0


def test_multiple_breaches_in_one_snapshot():
    opening = {"home": 2.00, "draw": 3.00, "away": 4.00}
    current = {"home": 2.20, "draw": 3.50, "away": 3.20}  # +10%, +16.67%, -20%
    breaches = compute_breaches(opening, current, "football", threshold_pct=5.0)
    keys = {b.dedupe_key for b in breaches}
    assert keys == {"home_up", "draw_up", "away_down"}


def test_exactly_at_threshold_triggers():
    """5% threshold + exactly 5% move should fire (>=, not strict)."""
    opening = {"home": 2.00, "draw": 3.40, "away": 3.80}
    current = {"home": 2.10, "draw": 3.40, "away": 3.80}  # +5.0%
    breaches = compute_breaches(opening, current, "football", threshold_pct=5.0)
    assert len(breaches) == 1
    assert breaches[0].abs_pct_move == 5.0


# ────────────────────────────────────────────────────────────────────
# compute_breaches — tennis
# ────────────────────────────────────────────────────────────────────

def test_tennis_uses_player_markets():
    opening = {"player1": 1.50, "player2": 2.60}
    current = {"player1": 1.65, "player2": 2.60}  # +10% p1
    breaches = compute_breaches(opening, current, "tennis", threshold_pct=5.0)
    assert len(breaches) == 1
    assert breaches[0].market == "player1"


def test_tennis_ignores_football_keys():
    """A football-shaped opening on a tennis match shouldn't crash or fire."""
    opening = {"home": 2.00, "draw": 3.40, "away": 3.80}
    current = {"player1": 1.50, "player2": 2.60}
    assert compute_breaches(opening, current, "tennis", threshold_pct=5.0) == []


# ────────────────────────────────────────────────────────────────────
# compute_breaches — robustness
# ────────────────────────────────────────────────────────────────────

def test_missing_market_skipped_not_error():
    opening = {"home": 2.00, "draw": None, "away": 3.80}
    current = {"home": 2.30, "away": 3.80}  # draw missing entirely
    breaches = compute_breaches(opening, current, "football", threshold_pct=5.0)
    assert len(breaches) == 1
    assert breaches[0].market == "home"


def test_zero_opening_odds_skipped():
    """Decimal odds <= 0 is nonsense — must not divide by zero."""
    opening = {"home": 0.0, "draw": 3.40, "away": 3.80}
    current = {"home": 2.20, "draw": 3.40, "away": 3.80}
    assert compute_breaches(opening, current, "football", threshold_pct=5.0) == []


def test_non_numeric_odds_skipped():
    opening = {"home": "n/a", "draw": 3.40, "away": 3.80}
    current = {"home": 2.20, "draw": 3.40, "away": 3.80}
    assert compute_breaches(opening, current, "football", threshold_pct=5.0) == []


def test_zero_threshold_yields_no_breaches():
    opening = {"home": 2.00, "draw": 3.40, "away": 3.80}
    current = {"home": 2.20, "draw": 3.40, "away": 3.80}
    assert compute_breaches(opening, current, "football", threshold_pct=0.0) == []


def test_negative_threshold_yields_no_breaches():
    """Negative threshold is a misconfigured user — don't spam them."""
    opening = {"home": 2.00, "draw": 3.40, "away": 3.80}
    current = {"home": 2.20, "draw": 3.40, "away": 3.80}
    assert compute_breaches(opening, current, "football", threshold_pct=-1.0) == []


# ────────────────────────────────────────────────────────────────────
# format_alert_message
# ────────────────────────────────────────────────────────────────────

def test_format_includes_teams_and_breach():
    msg = format_alert_message(
        home_team="Arsenal",
        away_team="Chelsea",
        sport="football",
        breaches=[MovementBreach("home", "up", 2.00, 2.20, 10.0)],
        bookmaker="Bet365",
        threshold_pct=5.0,
    )
    assert "Arsenal" in msg
    assert "Chelsea" in msg
    assert "Home" in msg
    assert "2.00" in msg
    assert "2.20" in msg
    assert "10.0%" in msg
    assert "Bet365" in msg


def test_format_uses_player_labels_for_tennis():
    msg = format_alert_message(
        home_team="Alcaraz",
        away_team="Sinner",
        sport="tennis",
        breaches=[MovementBreach("player1", "down", 1.80, 1.60, 11.11)],
        bookmaker=None,
        threshold_pct=5.0,
    )
    assert "Alcaraz" in msg
    assert "▼" in msg  # down arrow
    assert "Source" not in msg  # bookmaker omitted when None


def test_format_handles_missing_team_names():
    msg = format_alert_message(
        home_team=None,
        away_team=None,
        sport="football",
        breaches=[MovementBreach("draw", "up", 3.00, 3.30, 10.0)],
        bookmaker="Pinnacle",
        threshold_pct=5.0,
    )
    assert "Home" in msg and "Away" in msg  # fallback labels in title
    assert "Draw" in msg
