"""
Client for The Odds API — fetches sharp bookmaker odds for a given event.

Only used when ODDS_API_KEY env var is set. Completely optional;
the odds tracker works with FlashScore alone if no key is configured.
"""
import datetime
import logging
import os
import re
from typing import Optional

import httpx
import redis as sync_redis

logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"

# ---------------------------------------------------------------------------
# Usage counters (consumed by /admin/info).
#
# Every outbound Odds API call goes through ``_counted_get`` which bumps a
# Redis lifetime counter plus a per-day counter (so the admin dashboard can
# show today's spend without crunching a log file). A sync Redis client is
# fine here — these calls already run inside ``run_in_executor`` from the
# odds scheduler, so we're off the asyncio loop.
#
# Failures (Redis down, etc.) are swallowed: monitoring must never break the
# main API path.
# ---------------------------------------------------------------------------
ODDS_API_TOTAL_KEY = "odds_api:calls:total"
ODDS_API_DAILY_KEY_PREFIX = "odds_api:calls:"
# 35 days of daily-call history is enough to see a billing cycle while keeping
# the keyspace bounded.
ODDS_API_DAILY_TTL_SECONDS = 35 * 86400

_sync_redis_client: Optional[sync_redis.Redis] = None


def _get_sync_redis() -> Optional[sync_redis.Redis]:
    """Lazy-init a small sync Redis client just for usage counters.

    Mirrors the host/port used by the async app client (see app/core/config.py).
    """
    global _sync_redis_client
    if _sync_redis_client is not None:
        return _sync_redis_client
    try:
        host = os.environ.get("REDIS_HOST", "localhost")
        _sync_redis_client = sync_redis.Redis(host=host, port=6379, db=0, decode_responses=True)
    except Exception as e:
        logger.debug("Sync Redis init for Odds API counter failed: %s", e)
        _sync_redis_client = None
    return _sync_redis_client


def _record_api_call() -> None:
    """Increment the lifetime + today counters. Best-effort; never raises."""
    client = _get_sync_redis()
    if client is None:
        return
    try:
        today_key = ODDS_API_DAILY_KEY_PREFIX + datetime.date.today().isoformat()
        pipe = client.pipeline()
        pipe.incr(ODDS_API_TOTAL_KEY)
        pipe.incr(today_key)
        pipe.expire(today_key, ODDS_API_DAILY_TTL_SECONDS)
        pipe.execute()
    except Exception as e:
        logger.debug("Failed to record Odds API call counter: %s", e)


def _counted_get(url: str, params: dict, timeout: int = 15) -> httpx.Response:
    """Wrapper around ``httpx.get`` that bumps the usage counters first.

    Counting before the request (rather than after) means we still attribute
    a call we paid for to the user even if the response is non-200 — The Odds
    API counts failed requests against the quota too.
    """
    _record_api_call()
    return httpx.get(url, params=params, timeout=timeout)

# Sharp bookmakers whose odds we want to capture alongside FlashScore
SHARP_BOOKMAKERS = ["pinnacle", "betfair_ex_eu", "betonlineag"]

# Regions requested from The Odds API on every odds call.
#
# COST: The Odds API bills (number of markets) × (number of regions) per call,
# so each region is a full multiplier on every request. We default to "eu"
# only — our sharp books (Pinnacle, Betfair EU) and the soft books we display
# (Betclic, Bet365) are all EU-listed, so adding "us" doubled the spend for
# near-zero extra coverage. Override with ODDS_API_REGIONS (comma-separated,
# e.g. "eu,uk") only if you genuinely need another region's books.
# See SPECS.md §6 for the full cost model.
ODDS_API_REGIONS = os.environ.get("ODDS_API_REGIONS", "eu").strip() or "eu"

# Regex for valid Odds API sport keys: e.g. "soccer_epl", "tennis_atp"
_SPORT_KEY_RE = re.compile(r'^[a-z][a-z0-9]+(_[a-z][a-z0-9]+)+$')

# Major soccer leagues to search when sport_key is not provided
SOCCER_SPORT_KEYS = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_netherlands_eredivisie",
    "soccer_portugal_primeira_liga",
    "soccer_turkey_super_league",
]

# Tennis: The Odds API uses tournament-specific keys (e.g. "tennis_atp_miami_open",
# "tennis_wta_indian_wells") — there is no generic "tennis_atp" endpoint.
# Users must supply the exact sport_key when tracking tennis matches.
TENNIS_SPORT_KEYS: list[str] = []

# Map sport name → default keys list
_DEFAULT_KEYS_BY_SPORT = {
    "tennis": TENNIS_SPORT_KEYS,
    "football": SOCCER_SPORT_KEYS,
}

# User-friendly aliases → Odds API sport keys
SPORT_KEY_ALIASES = {
    # Football
    "premier_league": "soccer_epl",
    "epl": "soccer_epl",
    "la_liga": "soccer_spain_la_liga",
    "bundesliga": "soccer_germany_bundesliga",
    "serie_a": "soccer_italy_serie_a",
    "ligue_1": "soccer_france_ligue_one",
    "champions_league": "soccer_uefa_champs_league",
    "europa_league": "soccer_uefa_europa_league",
    "eredivisie": "soccer_netherlands_eredivisie",
    "primeira_liga": "soccer_portugal_primeira_liga",
    "super_lig": "soccer_turkey_super_league",
    # Tennis — no aliases; users pass the full tournament key
    # e.g. "tennis_atp_miami_open", "tennis_wta_indian_wells"
}


def resolve_sport_key(sport_key: Optional[str]) -> Optional[str]:
    """Resolve a user-friendly alias to the Odds API sport key.

    Accepts: 'champions_league', 'la_liga', 'atp', 'soccer_epl', etc.
    Returns the real Odds API key or None if unrecognized.
    """
    if not sport_key:
        return None
    key = sport_key.strip().lower()
    # Check alias first
    if key in SPORT_KEY_ALIASES:
        return SPORT_KEY_ALIASES[key]
    # Already a valid Odds API key
    if _SPORT_KEY_RE.match(key):
        return key
    return None


def _is_valid_sport_key(sport_key: Optional[str]) -> bool:
    """Return True if sport_key is a valid Odds API key or a known alias."""
    if not sport_key:
        return False
    return resolve_sport_key(sport_key) is not None


def _normalize(name: str) -> str:
    """Lowercase + strip for fuzzy-ish comparison."""
    return name.strip().lower()


def _extract_surname(name: str) -> str:
    """Extract the surname from a player name.

    FlashScore format: 'Kouame M.' → 'Kouame' (first token, initial at end).
    Full name format: 'Maxime Kouame' → 'Kouame' (last token).
    """
    parts = name.split()
    if not parts:
        return name
    # FlashScore: "Kouame M." — surname is first token
    if len(parts) >= 2 and len(parts[-1].rstrip(".")) <= 2:
        return parts[0]
    # Full name: "Maxime Kouame" — surname is last token
    return parts[-1]


def _name_matches(a: str, b: str) -> bool:
    """Check if two names refer to the same entity (case-insensitive, substring)."""
    na, nb = _normalize(a), _normalize(b)
    return na in nb or nb in na


def _surname_matches(a: str, b: str) -> bool:
    """Check if two player names share the same surname."""
    sa = _normalize(_extract_surname(a))
    sb = _normalize(_extract_surname(b))
    return sa == sb and len(sa) >= 3


def _teams_match(api_home: str, api_away: str, home: str, away: str) -> bool:
    """Check if Odds API team names match the target (case-insensitive, substring)."""
    return _name_matches(api_home, home) and _name_matches(api_away, away)


def find_event(
    api_key: str,
    home_team: str,
    away_team: str,
    sport_key: Optional[str] = None,
    sport: str = "football",
) -> Optional[tuple[str, str, Optional[str]]]:
    """
    Search The Odds API events for a match matching the given team/player names.

    Returns (event_id, sport_key, commence_time_iso) or None if no match found.
    ``commence_time_iso`` is the event's UTC ISO 8601 kickoff string from
    The Odds API (e.g. ``"2026-04-26T19:00:00Z"``); may be None if absent.

    - sport_key accepts aliases ('champions_league', 'la_liga', 'atp') or
      raw Odds API keys ('soccer_epl'). See SPORT_KEY_ALIASES.
    - If sport_key is not provided, searches all keys for the given sport.
    """
    resolved = resolve_sport_key(sport_key)
    if resolved:
        keys_to_search = [resolved]
    else:
        # Ignore invalid/placeholder values like "string" — use sport defaults
        if sport_key and not _is_valid_sport_key(sport_key):
            logger.info("Ignoring invalid sport_key '%s', using sport=%s defaults.", sport_key, sport)
        keys_to_search = _DEFAULT_KEYS_BY_SPORT.get(sport, SOCCER_SPORT_KEYS)
        if not keys_to_search:
            logger.warning(
                "No sport_key provided for sport=%s. Tennis requires a tournament-specific "
                "key (e.g. 'tennis_atp_miami_open'). Skipping Odds API lookup.",
                sport,
            )
            return None

    for sk in keys_to_search:
        try:
            url = f"{BASE_URL}/sports/{sk}/events"
            resp = _counted_get(url, params={"apiKey": api_key}, timeout=15)
            if resp.status_code != 200:
                logger.warning("Odds API events returned %s for %s", resp.status_code, sk)
                continue

            events = resp.json()
            if not isinstance(events, list):
                continue

            # Pass 1: both teams match (strong match)
            for event in events:
                api_home = event.get("home_team", "")
                api_away = event.get("away_team", "")
                if _teams_match(api_home, api_away, home_team, away_team):
                    event_id = event["id"]
                    commence_time = event.get("commence_time")
                    logger.info(
                        "Matched '%s vs %s' → event %s in %s (commence_time=%s)",
                        home_team, away_team, event_id, sk, commence_time,
                    )
                    return event_id, sk, commence_time

            # Pass 2: single-team match — if exactly one event matches
            # either team name, use it (handles abbreviations like PSG)
            single_matches = []
            for event in events:
                api_home = event.get("home_team", "")
                api_away = event.get("away_team", "")
                either_home = _name_matches(api_home, home_team) or _name_matches(api_away, home_team)
                either_away = _name_matches(api_home, away_team) or _name_matches(api_away, away_team)
                if either_home or either_away:
                    single_matches.append(event)

            if len(single_matches) == 1:
                event = single_matches[0]
                event_id = event["id"]
                commence_time = event.get("commence_time")
                logger.info(
                    "Single-team matched '%s vs %s' → event %s (%s vs %s) in %s (commence_time=%s)",
                    home_team, away_team, event_id,
                    event.get("home_team"), event.get("away_team"), sk, commence_time,
                )
                return event_id, sk, commence_time

            # Pass 3: surname match — handles FlashScore 'Kouame M.' vs
            # Odds API 'Maxime Kouame' by comparing extracted surnames
            surname_matches = []
            for event in events:
                api_home = event.get("home_team", "")
                api_away = event.get("away_team", "")
                if (_surname_matches(api_home, home_team)
                        and _surname_matches(api_away, away_team)):
                    surname_matches.append(event)

            if len(surname_matches) == 1:
                event = surname_matches[0]
                event_id = event["id"]
                commence_time = event.get("commence_time")
                logger.info(
                    "Surname matched '%s vs %s' → event %s (%s vs %s) in %s (commence_time=%s)",
                    home_team, away_team, event_id,
                    event.get("home_team"), event.get("away_team"), sk, commence_time,
                )
                return event_id, sk, commence_time

        except Exception as e:
            logger.warning("Error searching events in %s: %s", sk, e)
            continue

    logger.info("No Odds API event found for '%s vs %s'.", home_team, away_team)
    return None


def extract_sharp_odds_from_event(
    event_data: dict,
    home_team: str,
    away_team: str,
) -> dict[str, dict]:
    """
    Given raw event data (with bookmakers), extract H2H odds
    from sharp bookmakers only.

    Works for both football (home/draw/away) and tennis (home/away, no draw).

    Returns e.g.:
        {
            "pinnacle": {"home": 2.50, "draw": 3.20, "away": 2.80},   # football
            "pinnacle": {"home": 2.55, "away": 1.55},                  # tennis
        }
    """
    result = {}
    h_norm = _normalize(home_team)
    a_norm = _normalize(away_team)
    # Odds API home/away from the event data itself (authoritative names)
    api_home_norm = _normalize(event_data.get("home_team", ""))
    api_away_norm = _normalize(event_data.get("away_team", ""))

    for bm in event_data.get("bookmakers", []):
        bm_key = bm.get("key", "")
        if bm_key not in SHARP_BOOKMAKERS:
            continue

        for market in bm.get("markets", []):
            if market.get("key") != "h2h":
                continue

            odds_map = {}
            for outcome in market.get("outcomes", []):
                name = _normalize(outcome.get("name", ""))
                price = outcome.get("price")
                if price is None:
                    continue

                if name == "draw":
                    odds_map["draw"] = price
                elif _name_matches(name, h_norm):
                    odds_map["home"] = price
                elif _name_matches(name, a_norm):
                    odds_map["away"] = price
                # Fallback: match against the Odds API's own team names
                elif _name_matches(name, api_home_norm):
                    odds_map["home"] = price
                elif _name_matches(name, api_away_norm):
                    odds_map["away"] = price

            if "home" in odds_map and "away" in odds_map:
                result[bm_key] = odds_map

    return result


def get_event_commence_time(
    api_key: str,
    sport_key: str,
    event_id: str,
) -> Optional[str]:
    """Fetch the latest ``commence_time`` for an Odds API event.

    Used to refresh stored kickoff times so postponements/delays propagate.
    Returns the UTC ISO 8601 string from the events list endpoint, or None
    on any error / missing event.
    """
    try:
        url = f"{BASE_URL}/sports/{sport_key}/events"
        resp = _counted_get(url, params={"apiKey": api_key}, timeout=15)
        if resp.status_code != 200:
            logger.warning(
                "Odds API events returned %s when refreshing commence_time for %s/%s",
                resp.status_code, sport_key, event_id,
            )
            return None
        events = resp.json()
        if not isinstance(events, list):
            return None
        for event in events:
            if event.get("id") == event_id:
                return event.get("commence_time")
        return None
    except Exception as e:
        logger.warning("Failed to refresh commence_time for %s/%s: %s", sport_key, event_id, e)
        return None


def fetch_event_scores(
    api_key: str,
    sport_key: str,
    event_id: str,
    home_team: str,
    away_team: str,
    days_from: int = 1,
) -> Optional[dict]:
    """Fetch the final score for an Odds API event.

    Returns ``{"completed": bool, "home_score": int|None, "away_score": int|None}``
    or ``None`` if the event isn't in the response (the scores feed is
    eventually consistent — the event may not appear for a few minutes after
    full-time).

    The Odds API ``/scores`` endpoint returns a list of events for the sport,
    each with a ``scores`` array keyed by team name. We map those team-name
    entries back to home/away using the names stored on the tracked match.
    """
    try:
        url = f"{BASE_URL}/sports/{sport_key}/scores"
        params = {
            "apiKey": api_key,
            "daysFrom": days_from,
            "eventIds": event_id,
        }
        resp = _counted_get(url, params=params, timeout=15)
        if resp.status_code != 200:
            logger.warning(
                "Odds API scores returned %s for %s/%s",
                resp.status_code, sport_key, event_id,
            )
            return None

        events = resp.json()
        if not isinstance(events, list):
            return None

        for event in events:
            if event.get("id") != event_id:
                continue

            completed = bool(event.get("completed"))
            scores = event.get("scores") or []

            home_score: Optional[int] = None
            away_score: Optional[int] = None
            api_home = event.get("home_team", "")
            api_away = event.get("away_team", "")

            for entry in scores:
                name = entry.get("name", "")
                raw_score = entry.get("score")
                if raw_score is None or raw_score == "":
                    continue
                try:
                    parsed = int(raw_score)
                except (TypeError, ValueError):
                    continue
                # Match by Odds API team names first (authoritative), then
                # by the caller-provided names as a fallback.
                if _name_matches(name, api_home) or _name_matches(name, home_team):
                    home_score = parsed
                elif _name_matches(name, api_away) or _name_matches(name, away_team):
                    away_score = parsed

            return {
                "completed": completed,
                "home_score": home_score,
                "away_score": away_score,
            }

        return None
    except Exception as e:
        logger.warning("Failed to fetch scores for %s/%s: %s", sport_key, event_id, e)
        return None


def fetch_sharp_odds(
    api_key: str,
    sport_key: str,
    event_id: str,
    home_team: str,
    away_team: str,
) -> dict[str, dict]:
    """
    Fetch odds for a specific event from The Odds API,
    filtered to sharp bookmakers.

    Returns dict keyed by bookmaker name, or {} on failure.
    """
    try:
        url = f"{BASE_URL}/sports/{sport_key}/events/{event_id}/odds"
        params = {
            "apiKey": api_key,
            "regions": ODDS_API_REGIONS,
            "markets": "h2h",
            "oddsFormat": "decimal",
            "bookmakers": ",".join(SHARP_BOOKMAKERS),
        }
        resp = _counted_get(url, params=params, timeout=15)
        if resp.status_code != 200:
            logger.warning(
                "Odds API event odds returned %s for %s/%s",
                resp.status_code, sport_key, event_id,
            )
            return {}

        event_data = resp.json()
        return extract_sharp_odds_from_event(event_data, home_team, away_team)

    except Exception as e:
        logger.warning("Failed to fetch sharp odds for %s: %s", event_id, e)
        return {}


# Preference order for picking the "primary" bookmaker on a totals snapshot.
# Pinnacle is the sharpest book and the most stable line — pick it first.
# Bet365 and Betclic are soft books carried by The Odds API and broadly
# available across regions, so they're the natural fallbacks if Pinnacle
# isn't offering the requested line for a given match (rare but possible
# for obscure fixtures).
TOTALS_PRIMARY_BOOKMAKERS = (
    "pinnacle",
    "bet365",
    "betclic",
    "betfair_ex_eu",
    "williamhill",
    "betonlineag",
)


def extract_totals_from_event(
    event_data: dict,
    line: float,
) -> dict:
    """Pull O/U odds for ``line`` (e.g. 2.5) out of a /events/{id}/odds
    response that was requested with ``markets=totals``.

    Returns the same shape the scheduler / persistence layer expects::

        {
            "line": 2.5,
            "over": 1.92,
            "under": 1.95,
            "bookmaker": "pinnacle",
            "source_url": None,  # API-sourced, no FlashScore URL
            "available_books": ["pinnacle", "bet365", ...],
        }

    Picks the first bookmaker (in :data:`TOTALS_PRIMARY_BOOKMAKERS` order)
    that quotes both Over and Under for the requested line. Returns
    ``{}`` if no listed book quotes that line — the caller treats this as
    "no valid odds this tick" and the scheduler will retry next cycle.
    """
    # Bucket: bookmaker_key → {"over": price|None, "under": price|None}
    by_book: dict[str, dict[str, float]] = {}
    available_books: list[str] = []

    for bm in event_data.get("bookmakers", []) or []:
        bm_key = bm.get("key") or ""
        if not bm_key:
            continue
        for market in bm.get("markets", []) or []:
            if market.get("key") != "totals":
                continue
            for outcome in market.get("outcomes", []) or []:
                # The Odds API encodes the line in ``point`` and uses
                # Title-case "Over"/"Under" in ``name``.
                try:
                    point = float(outcome.get("point"))
                except (TypeError, ValueError):
                    continue
                if abs(point - line) > 1e-6:
                    continue
                name = (outcome.get("name") or "").strip().lower()
                price = outcome.get("price")
                if price is None or name not in ("over", "under"):
                    continue
                try:
                    price_f = float(price)
                except (TypeError, ValueError):
                    continue
                if price_f <= 1.0:
                    # Sanity guard: decimal odds <= 1 are nonsense; skip.
                    continue
                slot = by_book.setdefault(bm_key, {})
                slot[name] = price_f

        # Track every book that quoted the line, even if only one side.
        # Useful for logging — helps debug "why didn't Pinnacle have
        # this line on this match".
        if bm_key in by_book and bm_key not in available_books:
            available_books.append(bm_key)

    # Pick the first preferred book that has BOTH sides.
    for preferred in TOTALS_PRIMARY_BOOKMAKERS:
        slot = by_book.get(preferred)
        if slot and "over" in slot and "under" in slot:
            return {
                "line": line,
                "over": slot["over"],
                "under": slot["under"],
                "bookmaker": preferred,
                "source_url": None,
                "available_books": available_books,
            }

    # No preferred book had both sides — fall back to ANY book that did.
    # This keeps tracking working for obscure leagues where the sharps
    # might not be live.
    for bm_key, slot in by_book.items():
        if "over" in slot and "under" in slot:
            return {
                "line": line,
                "over": slot["over"],
                "under": slot["under"],
                "bookmaker": bm_key,
                "source_url": None,
                "available_books": available_books,
            }

    return {}


def fetch_totals_odds(
    api_key: str,
    sport_key: str,
    event_id: str,
    line: float = 2.5,
) -> dict:
    """Fetch Over/Under totals odds for ``event_id`` at ``line``.

    Single network call (markets=totals) so this costs ~1 Odds API credit
    per scrape per match. Same response shape FlashScore-scraped O/U
    snapshots used to produce, so the scheduler is callsite-compatible.

    Returns ``{}`` on any failure / missing line / 429 / network error;
    the scheduler treats that as "no valid odds this tick" and moves on.
    """
    try:
        url = f"{BASE_URL}/sports/{sport_key}/events/{event_id}/odds"
        params = {
            "apiKey": api_key,
            "regions": ODDS_API_REGIONS,
            "markets": "totals",
            "oddsFormat": "decimal",
            # Don't filter to sharp-only — for totals we want the broadest
            # bookmaker pool so the fallback in extract_totals_from_event
            # has options when Pinnacle doesn't carry the line.
        }
        resp = _counted_get(url, params=params, timeout=15)
        if resp.status_code != 200:
            logger.warning(
                "Odds API totals returned %s for %s/%s line=%s",
                resp.status_code, sport_key, event_id, line,
            )
            return {}

        event_data = resp.json()
        result = extract_totals_from_event(event_data, line=line)
        if result:
            logger.info(
                "Fetched totals %s for %s via %s: over=%s under=%s (books quoting: %s)",
                line, event_id, result["bookmaker"], result["over"], result["under"],
                len(result.get("available_books", [])),
            )
        else:
            logger.warning(
                "No bookmaker quoted both Over and Under at line %s for %s/%s",
                line, sport_key, event_id,
            )
        return result

    except Exception as e:
        logger.warning(
            "Failed to fetch totals odds for %s/%s line=%s: %s",
            sport_key, event_id, line, e,
        )
        return {}
