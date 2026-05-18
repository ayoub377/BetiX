"""Unit tests for the pure parts of the Odds API totals path.

The HTTP wrapper (``fetch_totals_odds``) is tested separately with a mock;
this file covers ``extract_totals_from_event`` since that's the function
that gets fed real Odds API JSON shape and decides which bookmaker /
outcomes win for a given line.
"""
from app.services.odds_api.odds_api_client import (
    TOTALS_PRIMARY_BOOKMAKERS,
    extract_totals_from_event,
)


def _make_event(*books: dict) -> dict:
    """Build a minimal Odds API ``/events/{id}/odds?markets=totals`` payload."""
    return {"bookmakers": list(books)}


def _make_totals_book(key: str, *, over_25: float | None = None,
                     under_25: float | None = None,
                     over_30: float | None = None,
                     under_30: float | None = None) -> dict:
    outcomes = []
    if over_25 is not None:
        outcomes.append({"name": "Over", "point": 2.5, "price": over_25})
    if under_25 is not None:
        outcomes.append({"name": "Under", "point": 2.5, "price": under_25})
    if over_30 is not None:
        outcomes.append({"name": "Over", "point": 3.0, "price": over_30})
    if under_30 is not None:
        outcomes.append({"name": "Under", "point": 3.0, "price": under_30})
    return {
        "key": key,
        "markets": [{"key": "totals", "outcomes": outcomes}],
    }


# ────────────────────────────────────────────────────────────────────
# Happy path — Pinnacle wins when present with both sides
# ────────────────────────────────────────────────────────────────────

def test_picks_pinnacle_when_it_has_both_sides_for_the_line():
    event = _make_event(
        _make_totals_book("pinnacle", over_25=1.92, under_25=1.95),
        _make_totals_book("bet365", over_25=1.88, under_25=1.90),
    )
    result = extract_totals_from_event(event, line=2.5)
    assert result["bookmaker"] == "pinnacle"
    assert result["over"] == 1.92
    assert result["under"] == 1.95
    assert result["line"] == 2.5
    assert result["source_url"] is None
    assert "pinnacle" in result["available_books"]
    assert "bet365" in result["available_books"]


def test_falls_back_to_bet365_when_pinnacle_only_quotes_one_side():
    """Pinnacle without Under at 2.5 → use Bet365."""
    event = _make_event(
        _make_totals_book("pinnacle", over_25=1.92),  # under missing
        _make_totals_book("bet365", over_25=1.88, under_25=1.90),
    )
    result = extract_totals_from_event(event, line=2.5)
    # Pinnacle was incomplete, so Bet365 wins.
    assert result["bookmaker"] == "bet365"
    assert result["over"] == 1.88
    assert result["under"] == 1.90


def test_uses_any_book_when_none_of_the_preferred_books_have_the_line():
    """Lower-tier leagues sometimes only have soft books in The Odds API."""
    event = _make_event(
        _make_totals_book("unibet_eu", over_25=2.05, under_25=1.78),
        _make_totals_book("nordicbet", over_25=2.10, under_25=1.75),
    )
    result = extract_totals_from_event(event, line=2.5)
    # Neither is in TOTALS_PRIMARY_BOOKMAKERS — pick whichever the dict
    # enumerated first (set semantics aside, we accept either as long as
    # the line is intact).
    assert result["bookmaker"] in {"unibet_eu", "nordicbet"}
    assert result["over"] > 1.0 and result["under"] > 1.0


# ────────────────────────────────────────────────────────────────────
# Line discrimination — must not cross-contaminate 2.5 with 3.0
# ────────────────────────────────────────────────────────────────────

def test_ignores_outcomes_at_other_lines():
    """Critical: a 3.0-only quote must not be returned as the 2.5 result."""
    event = _make_event(
        _make_totals_book("pinnacle", over_30=2.45, under_30=1.55),  # no 2.5
    )
    result = extract_totals_from_event(event, line=2.5)
    assert result == {}


def test_returns_correct_line_when_multiple_lines_present():
    event = _make_event(
        _make_totals_book(
            "pinnacle",
            over_25=1.92, under_25=1.95,
            over_30=2.45, under_30=1.55,
        ),
    )
    r25 = extract_totals_from_event(event, line=2.5)
    r30 = extract_totals_from_event(event, line=3.0)
    assert r25["over"] == 1.92 and r25["under"] == 1.95
    assert r30["over"] == 2.45 and r30["under"] == 1.55


# ────────────────────────────────────────────────────────────────────
# Robustness — malformed Odds API responses must not crash
# ────────────────────────────────────────────────────────────────────

def test_empty_event_returns_empty_dict():
    assert extract_totals_from_event({}, line=2.5) == {}
    assert extract_totals_from_event({"bookmakers": []}, line=2.5) == {}


def test_book_with_no_totals_market_skipped():
    event = {
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [{"key": "h2h", "outcomes": []}],  # wrong market
            },
        ]
    }
    assert extract_totals_from_event(event, line=2.5) == {}


def test_garbage_point_or_price_skipped():
    event = {
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [{"key": "totals", "outcomes": [
                    {"name": "Over", "point": "n/a", "price": 1.92},
                    {"name": "Under", "point": 2.5, "price": None},
                ]}],
            },
            _make_totals_book("bet365", over_25=1.88, under_25=1.90),
        ]
    }
    result = extract_totals_from_event(event, line=2.5)
    # Pinnacle had no valid outcomes after garbage filter → Bet365 wins.
    assert result["bookmaker"] == "bet365"


def test_decimal_odds_below_or_equal_one_rejected():
    """Odds <= 1.0 are nonsense (no positive payout); skip them."""
    event = _make_event(
        _make_totals_book("pinnacle", over_25=0.95, under_25=1.95),
    )
    assert extract_totals_from_event(event, line=2.5) == {}


def test_preferred_book_order_is_stable():
    """Sanity guard: Pinnacle must come first in the priority list.
    A reorder mistake would silently change which book becomes 'primary'
    on every match and would be hard to spot in production."""
    assert TOTALS_PRIMARY_BOOKMAKERS[0] == "pinnacle"
    assert "bet365" in TOTALS_PRIMARY_BOOKMAKERS
