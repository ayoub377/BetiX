"""Sanity tests for the central markets registry.

The registry is the source of truth several layers (scraper dispatcher,
scheduler iteration, Telegram dispatcher, API validators, frontend
discovery endpoint) read from. A typo here would break all of them
silently — these tests catch that.
"""
from app.models.markets import (
    DEFAULT_MARKETS,
    MARKET_1X2,
    MARKET_LABELS,
    MARKET_LINE,
    MARKET_OUTCOMES,
    MARKET_OU_2_5,
    SUPPORTED_MARKETS,
    is_supported,
    label_for,
    outcomes_for,
)


def test_supported_set_contains_known_ids():
    assert MARKET_1X2 in SUPPORTED_MARKETS
    assert MARKET_OU_2_5 in SUPPORTED_MARKETS


def test_default_markets_is_1x2_only_for_backward_compat():
    # Critical: legacy tracked matches that pre-date this PR must keep
    # behaving as 1X2-only. Don't add more defaults without an explicit
    # migration plan.
    assert DEFAULT_MARKETS == (MARKET_1X2,)


def test_every_supported_market_has_outcomes_label_and_line_entry():
    for market in SUPPORTED_MARKETS:
        assert market in MARKET_OUTCOMES, f"{market} missing from MARKET_OUTCOMES"
        assert market in MARKET_LABELS, f"{market} missing from MARKET_LABELS"
        assert market in MARKET_LINE, f"{market} missing from MARKET_LINE"
        outs = MARKET_OUTCOMES[market]
        assert len(outs) >= 2, f"{market} should have at least two outcomes"
        assert all(isinstance(o, str) and o for o in outs)


def test_1x2_outcomes_are_stable():
    """Snapshots and the Telegram dispatcher hard-code these names; if you
    rename them you must also update both call sites."""
    assert MARKET_OUTCOMES[MARKET_1X2] == ("home", "draw", "away")


def test_ou_2_5_outcomes_are_stable():
    assert MARKET_OUTCOMES[MARKET_OU_2_5] == ("over", "under")
    assert MARKET_LINE[MARKET_OU_2_5] == 2.5


def test_is_supported_rejects_unknown_ids():
    assert is_supported(MARKET_1X2) is True
    assert is_supported(MARKET_OU_2_5) is True
    assert is_supported("") is False
    assert is_supported("ou_3.5") is False  # not yet supported
    assert is_supported("btts") is False
    assert is_supported("nonsense") is False


def test_outcomes_for_unknown_market_returns_empty():
    # Critical for dispatcher safety: an unknown market id must not crash
    # the alert pipeline — it should just produce zero outcomes.
    assert outcomes_for("nope") == ()


def test_label_for_falls_back_to_id_for_unknown_market():
    assert label_for("nope") == "nope"
    assert label_for(MARKET_1X2) == "1X2 Full Time"
    assert label_for(MARKET_OU_2_5) == "Over/Under 2.5"
