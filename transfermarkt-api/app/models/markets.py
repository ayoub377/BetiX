"""Canonical market identifiers shared by the scraper, scheduler, API,
Telegram dispatcher and the frontend.

A "market" is a betting market type — e.g. 1X2 full-time, Over/Under 2.5
goals, Both Teams To Score. Each match snapshot belongs to exactly one
market; a tracked match can have several markets configured, and the
scheduler scrapes each one on every tick.

Wire format (str): we deliberately keep the wire format human-readable
(``"1x2"``, ``"ou_2.5"``) rather than opaque integers so logs, Redis
keys and frontend URLs stay easy to debug. Adding a new market is just:
  1. Append its id here and to MARKET_OUTCOMES.
  2. Teach the scraper to fetch it.
  3. The rest of the system flows through generically.
"""
from __future__ import annotations

from typing import Final

# ── Market identifiers ─────────────────────────────────────────────
# Keep snake_case; lines (e.g. 2.5) are appended with an underscore so
# the same shape works for OU 2.5, OU 3.5, AH -0.5 etc.

MARKET_1X2: Final[str] = "1x2"
MARKET_OU_2_5: Final[str] = "ou_2.5"

# All markets we currently support. Order is the display order on the
# frontend tabs.
SUPPORTED_MARKETS: Final[tuple[str, ...]] = (MARKET_1X2, MARKET_OU_2_5)

# Default for legacy rows / pre-multi-market callers — preserves the
# pre-PR behaviour of "everything is 1X2".
DEFAULT_MARKETS: Final[tuple[str, ...]] = (MARKET_1X2,)

# ── Outcome keys per market ────────────────────────────────────────
# Drives:
#   - the scraper's "which keys to populate"
#   - the Telegram alert dispatcher's "which fields to diff"
#   - the chart renderer's "which series to draw"
#
# Football-only for now. Tennis remains on its existing player1/player2
# 1X2-equivalent path; we'll generalise that when tennis grows markets.

MARKET_OUTCOMES: Final[dict[str, tuple[str, ...]]] = {
    MARKET_1X2: ("home", "draw", "away"),
    MARKET_OU_2_5: ("over", "under"),
}

# Human-readable labels for the frontend + alert messages. Frontend can
# override these if it wants localised strings, but the backend uses
# them in Telegram alert bodies.
MARKET_LABELS: Final[dict[str, str]] = {
    MARKET_1X2: "1X2 Full Time",
    MARKET_OU_2_5: "Over/Under 2.5",
}

# Numeric line (e.g. 2.5 for OU 2.5). None for markets without a line
# (1X2, BTTS).
MARKET_LINE: Final[dict[str, float | None]] = {
    MARKET_1X2: None,
    MARKET_OU_2_5: 2.5,
}


def is_supported(market: str) -> bool:
    """Whether ``market`` is one we currently know how to scrape + render.

    Use this at the API boundary; everything internal should already have
    validated the id.
    """
    return market in MARKET_OUTCOMES


def outcomes_for(market: str) -> tuple[str, ...]:
    """Outcome keys for ``market``. Empty tuple for unknown markets.

    Empty (instead of raising) keeps the Telegram dispatcher safe if a
    snapshot somehow carries a market id we removed — it just won't fire.
    """
    return MARKET_OUTCOMES.get(market, ())


def label_for(market: str) -> str:
    """Human label, or the raw id if unknown — never empty."""
    return MARKET_LABELS.get(market, market)
