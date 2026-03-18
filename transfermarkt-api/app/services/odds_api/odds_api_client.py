"""
Client for The Odds API — fetches sharp bookmaker odds for a given event.

Only used when ODDS_API_KEY env var is set. Completely optional;
the odds tracker works with FlashScore alone if no key is configured.
"""
import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"

# Sharp bookmakers whose odds we want to capture alongside FlashScore
SHARP_BOOKMAKERS = ["pinnacle", "betfair_ex_eu", "betonlineag"]

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


def _name_matches(a: str, b: str) -> bool:
    """Check if two names refer to the same entity (case-insensitive, substring)."""
    na, nb = _normalize(a), _normalize(b)
    return na in nb or nb in na


def _teams_match(api_home: str, api_away: str, home: str, away: str) -> bool:
    """Check if Odds API team names match the target (case-insensitive, substring)."""
    return _name_matches(api_home, home) and _name_matches(api_away, away)


def find_event(
    api_key: str,
    home_team: str,
    away_team: str,
    sport_key: Optional[str] = None,
    sport: str = "football",
) -> Optional[tuple[str, str]]:
    """
    Search The Odds API events for a match matching the given team/player names.

    Returns (event_id, sport_key) or None if no match found.

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
            resp = httpx.get(url, params={"apiKey": api_key}, timeout=15)
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
                    logger.info(
                        "Matched '%s vs %s' → event %s in %s",
                        home_team, away_team, event_id, sk,
                    )
                    return event_id, sk

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
                logger.info(
                    "Single-team matched '%s vs %s' → event %s (%s vs %s) in %s",
                    home_team, away_team, event_id,
                    event.get("home_team"), event.get("away_team"), sk,
                )
                return event_id, sk

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
            "regions": "eu,us",
            "markets": "h2h",
            "oddsFormat": "decimal",
            "bookmakers": ",".join(SHARP_BOOKMAKERS),
        }
        resp = httpx.get(url, params=params, timeout=15)
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
