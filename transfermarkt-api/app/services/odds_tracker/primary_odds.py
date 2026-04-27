"""
Resolve which bookmaker's prices the frontend should use as the canonical
"current odds" for the change indicator.

Pinnacle is the sharp/default source when present in a snapshot. We only fall
back to the FlashScore-scraped book (typically Betclic) when Pinnacle is absent
or incomplete — i.e., obscure leagues the Odds API doesn't cover.

The resolver is read-only: it never mutates stored snapshots. Endpoints call
``decorate_history()`` to enrich a list of raw snapshots with primary_source,
primary_odds, and the consecutive-snapshot delta.
"""
from typing import Optional


PINNACLE_KEY = "pinnacle"
FLASHSCORE_FALLBACK = "flashscore"


def _odds_for_sport(payload: dict, sport: str) -> Optional[dict]:
    """Pull the (home, draw, away) or (player1, player2) trio from a payload.

    Returns None when any required leg is missing or non-positive — partial
    Pinnacle data is treated as "not available" so we fall back to Betclic
    rather than render a half-formed price.
    """
    if not payload:
        return None

    if sport == "tennis":
        p1 = payload.get("player1")
        p2 = payload.get("player2")
        if p1 and p2 and p1 > 1.0 and p2 > 1.0:
            return {"player1": p1, "player2": p2}
        return None

    home = payload.get("home")
    draw = payload.get("draw")
    away = payload.get("away")
    if home and draw and away and home > 1.0 and draw > 1.0 and away > 1.0:
        return {"home": home, "draw": draw, "away": away}
    return None


def resolve_primary_odds(snapshot: dict) -> dict:
    """Return ``{"primary_source": ..., "primary_odds": {...}}`` for one snapshot.

    Pinnacle wins when ``snapshot["sharp_odds"]["pinnacle"]`` is complete;
    otherwise falls back to the snapshot's top-level FlashScore odds. The
    fallback ``primary_source`` is the snapshot's bookmaker name (lower-cased)
    so the frontend can display "Betclic" / "Bet365" / etc. accurately rather
    than always claiming "Betclic".
    """
    sport = snapshot.get("sport", "football")
    sharp = snapshot.get("sharp_odds") or {}
    pinnacle_payload = sharp.get(PINNACLE_KEY)

    pinnacle_odds = _odds_for_sport(pinnacle_payload, sport)
    if pinnacle_odds is not None:
        return {"primary_source": PINNACLE_KEY, "primary_odds": pinnacle_odds}

    fallback_odds = _odds_for_sport(snapshot, sport)
    if fallback_odds is not None:
        bookmaker = (snapshot.get("bookmaker") or FLASHSCORE_FALLBACK).strip().lower()
        return {"primary_source": bookmaker, "primary_odds": fallback_odds}

    return {"primary_source": None, "primary_odds": None}


def _diff_odds(current: dict, previous: dict) -> dict:
    """Per-key absolute delta. Caller guarantees the dicts share keys."""
    return {k: round(current[k] - previous[k], 4) for k in current.keys()}


def _pct_diff_odds(current: dict, previous: dict) -> dict:
    """Per-key percentage change. ``previous`` values are guaranteed > 1.0."""
    return {k: round((current[k] - previous[k]) / previous[k] * 100, 2) for k in current.keys()}


def decorate_history(history: list[dict]) -> list[dict]:
    """Enrich a chronological list of snapshots with primary_* fields.

    Each output snapshot gains:
    - primary_source: "pinnacle" | "<bookmaker name>" | None
    - primary_odds:   {home/draw/away} or {player1/player2} or None
    - primary_change: per-key absolute delta vs previous snapshot, or None
    - primary_change_pct: per-key percentage delta, or None

    ``primary_change`` is ``None`` whenever the source flips between
    consecutive snapshots — comparing a Pinnacle line to a Betclic line
    would surface a phantom move that has nothing to do with market action.
    """
    decorated: list[dict] = []
    prev_source: Optional[str] = None
    prev_odds: Optional[dict] = None

    for snapshot in history:
        resolved = resolve_primary_odds(snapshot)
        source = resolved["primary_source"]
        odds = resolved["primary_odds"]

        change = None
        change_pct = None
        if (
            odds is not None
            and prev_odds is not None
            and source == prev_source
            and odds.keys() == prev_odds.keys()
        ):
            change = _diff_odds(odds, prev_odds)
            change_pct = _pct_diff_odds(odds, prev_odds)

        decorated.append({
            **snapshot,
            "primary_source": source,
            "primary_odds": odds,
            "primary_change": change,
            "primary_change_pct": change_pct,
        })

        if odds is not None:
            prev_source = source
            prev_odds = odds

    return decorated
