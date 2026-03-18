import asyncio
import json
import logging
import os
from collections import defaultdict
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone
import uuid

import httpx
import shin
from fastapi import APIRouter, HTTPException, Depends
from dotenv import load_dotenv

from app.core import auth
from app.core.config import redis_client, rate_limit_dependency
from app.models.loader import fetch_club_id, fetch_club_players_data
from app.services.clubs.players import TransfermarktClubPlayers
from app.services.clubs.profile import TransfermarktClubProfile
from app.services.clubs.search import TransfermarktClubSearch
from app.services.clubs.attendance import TransfermarktClubAttendance
from app.services.clubs.staff import TransfermarktClubStaffs
from app.services.flashscore_scraper.scraper_factory import get_scraper
from app.models.sport import SportType
from app.utils.utils import parse_market_value
from starlette.responses import StreamingResponse

router = APIRouter()


class ProgressTracker:
    def __init__(self, home_team: str, away_team: str):
        self.home_team = home_team
        self.away_team = away_team
        self.progress: int = 0
        self.stage: str = "Initializing..."
        self.is_completed: bool = False  # renamed: no collision with method
        self.error_message: str | None = None  # renamed: no collision with method
        self._subscribers: List[asyncio.Queue] = []

    async def _broadcast(self, payload: dict):
        """Send payload to all live subscribers, dropping dead ones."""
        dead = []
        for queue in self._subscribers:
            try:
                await queue.put(payload)
            except Exception as e:
                logger.warning(f"Dropping dead subscriber: {e}")
                dead.append(queue)
        for queue in dead:
            self._subscribers.remove(queue)

    async def update(self, progress: int, stage: str):
        self.progress = progress
        self.stage = stage
        logger.debug(f"Progress {progress}%: {stage} | subscribers: {len(self._subscribers)}")
        await self._broadcast({"type": "progress", "progress": progress, "stage": stage})

    async def complete(self):
        self.is_completed = True
        self.progress = 100
        self.stage = "Analysis complete!"
        await self._broadcast({"type": "complete", "message": "Analysis finished"})

    async def fail(self, error_message: str):
        """Signal an error. Named 'fail' to avoid collision with error_message attr."""
        self.error_message = error_message
        await self._broadcast({"type": "error", "message": error_message})

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        logger.debug(f"Subscriber added ({len(self._subscribers)} total)")
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        try:
            self._subscribers.remove(queue)
            logger.debug(f"Subscriber removed ({len(self._subscribers)} remaining)")
        except ValueError:
            pass

    @property
    def is_done(self) -> bool:
        return self.is_completed or self.error_message is not None


logger = logging.getLogger(__name__)
# Signals that a tracker has been registered under a given key

_tracker_ready_events: Dict[str, asyncio.Event] = {}
progress_tasks: Dict[str, ProgressTracker] = {}


def register_tracker(progress_key: str, tracker: "ProgressTracker"):
    """
    Called by the analysis task BEFORE it starts work.
    Stores the tracker and signals any waiting SSE clients.
    """
    progress_tasks[progress_key] = tracker

    event = _tracker_ready_events.get(progress_key)
    if event:
        event.set()
    logger.debug(f"Tracker registered for key: {progress_key}")


def cleanup_tracker(progress_key: str):
    """Remove tracker and its ready-event after the stream is fully done."""
    progress_tasks.pop(progress_key, None)
    _tracker_ready_events.pop(progress_key, None)
    logger.debug(f"Tracker cleaned up for key: {progress_key}")


def calculate_shin_probabilities(odds_dict: Dict[str, float]) -> Dict[str, Dict[str, float]]:
    """
    Calculate Shin probabilities to remove vig from odds
    
    Args:
        odds_dict: Dictionary with team names as keys and decimal odds as values
        
    Returns:
        Dictionary with original odds, Shin probabilities, and vig-removed odds
    """
    print(f"DEBUG: calculate_shin_probabilities called with: {odds_dict}")
    try:
        # Filter out None/None values and convert to list
        valid_odds = [odd for odd in odds_dict.values() if odd is not None]
        team_names = [team for team, odd in odds_dict.items() if odd is not None]

        print(f"DEBUG: Valid odds: {valid_odds}")
        print(f"DEBUG: Team names: {team_names}")

        if len(valid_odds) < 2:
            print("DEBUG: Not enough valid odds for Shin calculation")
            return {}

        print(f"DEBUG: Calculating Shin probabilities for odds: {valid_odds}")

        # Calculate Shin probabilities
        shin_result = shin.calculate_implied_probabilities(valid_odds, full_output=True)

        # Create result dictionary
        result = {
            "original_odds": {},
            "shin_probabilities": {},
            "vig_removed_odds": {},
            "shin_metrics": {
                "z": shin_result.z,  # Insider proportion
                "iterations": shin_result.iterations,
                "delta": shin_result.delta
            }
        }

        # Populate results
        for i, team in enumerate(team_names):
            original_odd = valid_odds[i]
            shin_prob = shin_result.implied_probabilities[i]
            vig_removed_odd = 1 / shin_prob if shin_prob > 0 else None

            result["original_odds"][team] = original_odd
            result["shin_probabilities"][team] = shin_prob
            result["vig_removed_odds"][team] = vig_removed_odd

        print(f"DEBUG: Shin calculation successful - Z: {shin_result.z:.4f}, Iterations: {shin_result.iterations}")
        return result

    except Exception as e:
        print(f"DEBUG: Error in Shin calculation: {e}")
        return {}


@router.get("/search/{club_name}")
def search_clubs(club_name: str, page_number: Optional[int] = 1) -> dict:
    tfmkt = TransfermarktClubSearch(query=club_name, page_number=page_number)
    found_clubs = tfmkt.search_clubs()
    return found_clubs


@router.get("/search/{club_name}/injured")
def get_club_injuries(club_name: str):
    # Fetch club IDs
    club1_id = fetch_club_id(club_name)

    if not club1_id:
        print("Could not fetch one or both club IDs.")
        return None

    # Fetch players data
    players_club1 = fetch_club_players_data(club1_id["id"])

    # The fultred players
    filtered_players = {
        club_name: [],

    }

    # Process players for the club
    if isinstance(players_club1, dict):
        # get the list in players key
        players_list = players_club1["players"]
        if isinstance(players_list, list):  # Ensure it's a list
            for player in players_list:
                # Ensure it is a dictionary
                if isinstance(player, dict) and 'status' in player:
                    # Check if the player's status is not "Team captain"
                    if player['status'] != "Team captain":
                        filtered_players[club_name].append(player)

    return filtered_players


async def fetch_pinnacle_odds(home_team: str, away_team: str) -> Optional[Dict[str, Any]]:
    """
    Fetch pre-match money line odds from The Odds API for Pinnacle bookmaker
    
    Args:
        home_team: Home team name (may be abbreviated)
        away_team: Away team name (may be abbreviated)
        
    Returns:
        Dictionary with odds data or None if not found/error
    """
    print(f"DEBUG: fetch_pinnacle_odds called for {home_team} vs {away_team}")

    # Enhanced team name mapping for better matching
    TEAM_NAME_MAPPING = {
        # Premier League
        "arsenal": ["arsenal", "arsenal fc", "gunners"],
        "aston villa": ["aston villa", "villa", "avfc"],
        "bournemouth": ["bournemouth", "afc bournemouth", "cherries"],
        "brentford": ["brentford", "brentford fc", "bees"],
        "brighton": ["brighton", "brighton & hove albion", "seagulls"],
        "burnley": ["burnley", "burnley fc", "clarets"],
        "chelsea": ["chelsea", "chelsea fc", "blues"],
        "crystal palace": ["crystal palace", "palace", "eagles"],
        "everton": ["everton", "everton fc", "toffees"],
        "fulham": ["fulham", "fulham fc", "cottagers"],
        "liverpool": ["liverpool", "liverpool fc", "reds"],
        "luton": ["luton", "luton town", "hatters"],
        "man city": ["manchester city", "man city", "city", "sky blues"],
        "man utd": ["manchester united", "man utd", "united", "red devils"],
        "newcastle": ["newcastle united", "newcastle", "magpies"],
        "nottingham forest": ["nottingham forest", "forest", "tricky trees"],
        "sheffield utd": ["sheffield united", "sheffield utd", "blades"],
        "tottenham": ["tottenham hotspur", "tottenham", "spurs"],
        "west ham": ["west ham united", "west ham", "hammers"],
        "wolves": ["wolverhampton wanderers", "wolves", "wanderers"],

        # La Liga
        "alaves": ["deportivo alaves", "alaves"],
        "almeria": ["ud almeria", "almeria"],
        "athletic": ["athletic bilbao", "athletic", "bilbao"],
        "atletico": ["atletico madrid", "atletico", "colchoneros"],
        "barcelona": ["fc barcelona", "barcelona", "barca"],
        "betis": ["real betis", "betis", "verdiblancos"],
        "cadiz": ["cadiz cf", "cadiz"],
        "celta": ["rc celta", "celta", "celticos"],
        "getafe": ["getafe cf", "getafe"],
        "girona": ["girona fc", "girona"],
        "granada": ["granada cf", "granada"],
        "las palmas": ["ud las palmas", "las palmas"],
        "mallorca": ["rcd mallorca", "mallorca"],
        "osasuna": ["ca osasuna", "osasuna"],
        "rayo": ["rayo vallecano", "rayo"],
        "real madrid": ["real madrid", "madrid", "los blancos"],
        "sevilla": ["sevilla fc", "sevilla"],
        "sociedad": ["real sociedad", "sociedad", "txuri-urdin"],
        "valencia": ["valencia cf", "valencia", "che"],
        "villarreal": ["villarreal cf", "villarreal", "yellow submarine"],

        # Serie A
        "atalanta": ["atalanta bc", "atalanta", "nerazzurri"],
        "bologna": ["bologna fc", "bologna", "rossoblu"],
        "cagliari": ["cagliari calcio", "cagliari"],
        "empoli": ["empoli fc", "empoli"],
        "fiorentina": ["acf fiorentina", "fiorentina", "viola"],
        "frosinone": ["frosinone calcio", "frosinone"],
        "genoa": ["genoa cfc", "genoa", "grifone"],
        "inter": ["inter milan", "inter", "nerazzurri"],
        "juventus": ["juventus fc", "juventus", "old lady"],
        "lazio": ["ss lazio", "lazio", "biancocelesti"],
        "lecce": ["us lecce", "lecce"],
        "milan": ["ac milan", "milan", "rossoneri"],
        "monza": ["ac monza", "monza"],
        "napoli": ["ssc napoli", "napoli", "partenopei"],
        "roma": ["as roma", "roma", "giallorossi"],
        "salernitana": ["us salernitana", "salernitana"],
        "sassuolo": ["us sassuolo", "sassuolo", "neroverdi"],
        "torino": ["torino fc", "torino", "granata"],
        "udinese": ["udinese calcio", "udinese"],
        "verona": ["hellas verona", "verona", "gialloblu"],

        # Bundesliga
        "bayern": ["bayern munich", "bayern", "fcb"],
        "dortmund": ["borussia dortmund", "dortmund", "bvb"],
        "leipzig": ["rb leipzig", "leipzig", "die roten bullen"],
        "leverkusen": ["bayer leverkusen", "leverkusen", "die werkself"],
        "stuttgart": ["vfb stuttgart", "stuttgart"],
        "frankfurt": ["eintracht frankfurt", "frankfurt", "sge"],
        "hoffenheim": ["tsg 1899 hoffenheim", "hoffenheim"],
        "freiburg": ["sc freiburg", "freiburg"],
        "wolfsburg": ["vfl wolfsburg", "wolfsburg", "die wölfe"],
        "mainz": ["1. fsv mainz 05", "mainz", "die nullfünfer"],
        "union berlin": ["1. fc union berlin", "union berlin", "union"],
        "augsburg": ["fc augsburg", "augsburg"],
        "werder": ["sv werder bremen", "werder", "werder bremen"],
        "bochum": ["vfl bochum", "bochum"],
        "koln": ["1. fc koln", "koln", "cologne"],
        "heidenheim": ["1. fc heidenheim", "heidenheim"],
        "darmstadt": ["sv darmstadt 98", "darmstadt"],

        # Ligue 1
        "psg": ["paris saint-germain", "psg", "paris"],
        "monaco": ["as monaco", "monaco"],
        "lyon": ["olympique lyonnais", "lyon", "les gones"],
        "marseille": ["olympique de marseille", "marseille", "l'om"],
        "lille": ["losc lille", "lille"],
        "rennes": ["stade rennais", "rennes"],
        "strasbourg": ["rc strasbourg", "strasbourg"],
        "nice": ["ogc nice", "nice"],
        "reims": ["stade de reims", "reims"],
        "nantes": ["fc nantes", "nantes"],
        "toulouse": ["toulouse fc", "toulouse"],
        "lens": ["rc lens", "lens"],
        "brest": ["stade brestois", "brest"],
        "le havre": ["le havre ac", "le havre"],
        "metz": ["fc metz", "metz"],
        "clermont": ["clermont foot", "clermont"],
        "montpellier": ["montpellier hsc", "montpellier"],
        "lorient": ["fc lorient", "lorient"],
        "troyes": ["estac troyes", "troyes"],
        "ajaccio": ["ac ajaccio", "ajaccio"],

        # Eredivisie
        "ajax": ["afc ajax", "ajax"],
        "psv": ["psv eindhoven", "psv"],
        "feyenoord": ["feyenoord", "de club van het volk"],
        "az": ["az alkmaar", "az"],
        "twente": ["fc twente", "twente"],
        "sparta": ["sparta rotterdam", "sparta"],
        "utrecht": ["fc utrecht", "utrecht"],
        "heerenveen": ["sc heerenveen", "heerenveen"],
        "vitesse": ["vitesse arnhem", "vitesse"],
        "groningen": ["fc groningen", "groningen"],
        "heracles": ["heracles almelo", "heracles"],
        "volendam": ["fc volendam", "volendam"],
        "excelsior": ["sbv excelsior", "excelsior"],
        "almere": ["almere city fc", "almere"],
        "waalwijk": ["rkc waalwijk", "waalwijk"],
        "fortuna": ["fortuna sittard", "fortuna"],
        "pec": ["pec zwolle", "pec zwolle"],
        "go ahead": ["go ahead eagles", "go ahead"],
        "cambuur": ["sc cambuur", "cambuur"],
        "emmen": ["fc emmen", "emmen"]
    }

    def normalize_team_name(team_name: str) -> List[str]:
        """Normalize team name and return possible variations"""
        team_lower = team_name.lower().strip()

        # Direct match in mapping
        for full_name, variations in TEAM_NAME_MAPPING.items():
            if team_lower in variations or team_lower == full_name:
                return [full_name] + variations

        # Check if any variation contains our team name
        for full_name, variations in TEAM_NAME_MAPPING.items():
            if any(team_lower in var for var in variations) or any(var in team_lower for var in variations):
                return [full_name] + variations

        # If no match found, return the original name and some common variations
        return [team_name, team_lower]

    # def find_team_match(team_name: str, api_team_name: str) -> bool:
    #     """Enhanced team matching logic"""
    #     team_variations = normalize_team_name(team_name)
    #     api_team_lower = api_team_name.lower()
    #
    #     # Check if any variation matches
    #     for variation in team_variations:
    #         if (variation.lower() in api_team_lower or
    #             api_team_lower in variation.lower() or
    #             variation.lower() == api_team_lower):
    #             return True
    #
    #     # Additional fuzzy matching for common patterns
    #     # Remove common words and check
    #     api_clean = api_team_lower.replace('fc', '').replace('cf', '').replace('ac', '').replace('ud', '').replace('rc', '').replace('ss', '').replace('vfl', '').replace('tsg', '').replace('sv', '').replace('sbv', '').replace('sc', '').replace('as', '').replace('olympique', '').replace('stade', '').replace('deportivo', '').replace('real', '').replace('borussia', '').replace('bayer', '').replace('1.', '').replace('05', '').replace('98', '').replace('1899', '').strip()
    #
    #     for variation in team_variations:
    #         variation_clean = variation.lower().replace('fc', '').replace('cf', '').replace('ac', '').replace('ud', '').replace('rc', '').replace('ss', '').replace('vfl', '').replace('tsg', '').replace('sv', '').replace('sbv', '').replace('sc', '').replace('as', '').replace('olympique', '').replace('stade', '').replace('deportivo', '').replace('real', '').replace('borussia', '').replace('bayer', '').replace('1.', '').replace('05', '').replace('98', '').replace('1899', '').strip()
    #
    #         if (variation_clean in api_clean or
    #             api_clean in variation_clean or
    #             variation_clean == api_clean):
    #             return True
    #
    #     return False
    #
    # try:
    #     # Load API key from environment
    #     odds_api_key = os.getenv('ODDS_API_KEY')
    #     if not odds_api_key:
    #         print("WARNING: ODDS_API_KEY not found in environment variables")
    #         print("WARNING: Add ODDS_API_KEY to your .env file to enable odds fetching")
    #         print("WARNING: Get a free API key from: https://the-odds-api.com/")
    #         return None
    #
    #     print(f"DEBUG: Using API key ending with: ...{odds_api_key[-4:]}")
    #     print(f"DEBUG: Normalized home team variations: {normalize_team_name(home_team)}")
    #     print(f"DEBUG: Normalized away team variations: {normalize_team_name(away_team)}")
    #
    #     # Check cache first
    #     cache_key = f"odds:{home_team}:{away_team}"
    #     cached_odds = await redis_client.get(cache_key)
    #     if cached_odds:
    #         print(f"DEBUG: Found cached odds for {home_team} vs {away_team}")
    #         cached_data = json.loads(cached_odds)
    #
    #         # Always calculate Shin probabilities, even for cached odds
    #         if 'odds' in cached_data:
    #             print(f"DEBUG: Calculating Shin probabilities for cached odds: {cached_data['odds']}")
    #             shin_data = calculate_shin_probabilities(cached_data['odds'])
    #
    #             if shin_data:
    #                 cached_data['shin_analysis'] = shin_data
    #                 print(f"DEBUG: Added Shin analysis to cached data with Z={shin_data['shin_metrics']['z']:.4f}")
    #                 # Update cache with Shin analysis
    #                 await redis_client.setex(cache_key, 1800, json.dumps(cached_data))
    #                 print(f"DEBUG: Updated cache with Shin analysis")
    #             else:
    #                 print(f"DEBUG: Shin calculation failed for cached odds")
    #
    #             return cached_data
    #         else:
    #             print(f"DEBUG: Cached data missing odds, will recalculate")
    #             # Remove cached data to force fresh fetch
    #             await redis_client.delete(cache_key)
    #
    #     print(f"DEBUG: Fetching odds for {home_team} vs {away_team}")
    #
    #     # Common sport keys to try
    #     sport_keys = ['soccer_epl', 'soccer_spain_la_liga', 'soccer_italy_serie_a',
    #                  'soccer_germany_bundesliga', 'soccer_france_ligue_one', 'soccer_netherlands_eredivisie',]
    #
    #     best_match = None
    #
    #     async with httpx.AsyncClient(timeout=30.0) as client:
    #         for sport_key in sport_keys:
    #             try:
    #                 url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    #                 params = {
    #                     'apiKey': odds_api_key,
    #                     'regions': 'us',  # Pinnacle operates in US region
    #                     'markets': 'h2h',  # Money line (head to head)
    #                     'bookmakers': 'pinnacle',
    #                     'oddsFormat': 'decimal',
    #                     'dateFormat': 'iso'
    #                 }
    #
    #                 response = await client.get(url, params=params)
    #                 response.raise_for_status()
    #                 data = response.json()
    #
    #                 # Search for match in this sport
    #                 for game in data:
    #                     api_home_name = game.get('home_team', '')
    #                     api_away_name = game.get('away_team', '')
    #
    #                     print(f"DEBUG: Checking game: {api_home_name} vs {api_away_name}")
    #
    #                     # # Use enhanced team matching
    #                     # home_match = find_team_match(home_team, api_home_name)
    #                     # away_match = find_team_match(away_team, api_away_name)
    #                     #
    #                     # # Also check reverse order
    #                     # home_match_rev = find_team_match(home_team, api_away_name)
    #                     # away_match_rev = find_team_match(away_team, api_home_name)
    #
    #                     # print(f"DEBUG: Match results - Home: {home_match}, Away: {away_match}, Rev Home: {home_match_rev}, Rev Away: {away_match_rev}")
    #                     #
    #                     # if (home_match and away_match) or (home_match_rev and away_match_rev):
    #                     #     print(f"DEBUG: Found team match! Game: {api_home_name} vs {api_away_name}")
    #
    #                         # Check if this is a pre-match event (game hasn't started)
    #                         game_time = datetime.fromisoformat(game['commence_time'].replace('Z', '+00:00'))
    #                         current_time = datetime.now(timezone.utc)
    #
    #                         if game_time > current_time:
    #                             print(f"DEBUG: Game is pre-match, checking for Pinnacle odds")
    #                             # Find Pinnacle bookmaker odds
    #                             for bookmaker in game.get('bookmakers', []):
    #                                 if bookmaker.get('key') == 'pinnacle':
    #                                     for market in bookmaker.get('markets', []):
    #                                         if market.get('key') == 'h2h':
    #                                             outcomes = market.get('outcomes', [])
    #
    #                                             # Organize odds by team
    #                                             odds_data = {
    #                                                 'home_team': api_home_name,
    #                                                 'away_team': api_away_name,
    #                                                 'commence_time': game.get('commence_time'),
    #                                                 'sport_key': sport_key,
    #                                                 'sport_title': game.get('sport_title'),
    #                                                 'bookmaker': 'Pinnacle',
    #                                                 'odds': {}
    #                                             }
    #
    #                                             for outcome in outcomes:
    #                                                 team_name = outcome.get('name')
    #                                                 price = outcome.get('price')
    #                                                 odds_data['odds'][team_name] = price
    #
    #                                             print(f"DEBUG: Organized odds data: {odds_data}")
    #
    #                                             best_match = odds_data
    #                                             break
    #
    #                                     if best_match:
    #                                         break
    #
    #                             if best_match:
    #                                 break
    #
    #                 if best_match:
    #                     break
    #
    #             except Exception as e:
    #                 print(f"DEBUG: Error fetching odds for sport {sport_key}: {e}")
    #                 continue
    #
    #     if best_match:
    #         print(f"DEBUG: Found best match, about to calculate Shin probabilities")
    #         # Calculate Shin probabilities to remove vig
    #         print(f"DEBUG: Calculating Shin probabilities for odds: {best_match['odds']}")
    #         shin_data = calculate_shin_probabilities(best_match['odds'])
    #
    #         if shin_data:
    #             best_match['shin_analysis'] = shin_data
    #             print(f"DEBUG: Added Shin analysis with Z={shin_data['shin_metrics']['z']:.4f}")
    #             print(f"DEBUG: Shin analysis data: {json.dumps(shin_data, indent=2)}")
    #         else:
    #             print(f"DEBUG: Shin calculation failed, using original odds")
    #
    #         # Cache the odds for 30 minutes
    #         await redis_client.setex(cache_key, 1800, json.dumps(best_match))
    #         print(f"DEBUG: Successfully fetched and cached odds for {home_team} vs {away_team}")
    #         print(f"DEBUG: Final response includes shin_analysis: {'shin_analysis' in best_match}")
    #         return best_match
    #     else:
    #         print(f"DEBUG: No pre-match Pinnacle odds found for {home_team} vs {away_team}")
    #         return None
    #
    # except Exception as e:
    #     print(f"ERROR: Failed to fetch odds: {e}")
    #     return None


async def compare_players_with_lineup_and_substitutions(club_home_name: str, club_away_name: str,
                                                        lineups: Dict[str, Dict[str, str]],
                                                        substitutions: Dict[str, Dict] = None,
                                                        tracker: ProgressTracker = None):
    """
    Compare players' market value for a match using both starting lineup and substitution data.
    Lineups param: {"home_team": {"jersey_num_str": "player_name_str", ...}, "away_team": {...}}
    Substitutions param: {"home_team": {"substitutions": [...], "substituted_players": [...]}, "away_team": {...}}
    """
    print(f"Comparing lineups and substitutions for {club_home_name} vs {club_away_name}")
    print(f"Input Home Lineup Jersey Keys: {list(lineups.get('home_team', {}).keys())}")
    print(f"Input Away Lineup Jersey Keys: {list(lineups.get('away_team', {}).keys())}")

    print("DEBUG: Using Transfermarkt data only (FBref integration removed)")

    # Start fetching odds immediately in parallel with player comparison
    print(f"DEBUG: Starting odds fetch in parallel for {club_home_name} vs {club_away_name}")
    odds_task = asyncio.create_task(fetch_pinnacle_odds(club_home_name, club_away_name))

    # if tracker:
    #     await tracker.update(45, "Fetching club IDs from database...")

    # Fetch club IDs
    home_team_id = await fetch_club_id(club_home_name)
    away_team_id = await fetch_club_id(club_away_name)

    if not home_team_id or not away_team_id:
        if tracker:
            await tracker.fail(
                f"Unrecognized team(s) or ID not found: home team '{club_home_name}', away team '{club_away_name}'")
        raise HTTPException(status_code=404,
                            detail=f"Unrecognized team(s) or ID not found: home team '{club_home_name}', away team '{club_away_name}'")

    # if tracker:
    #     await tracker.update(50, "Fetching detailed player data...")

    # Fetch player data
    home_team_players_data = await fetch_club_players_data(home_team_id["id"])
    away_team_players_data = await fetch_club_players_data(away_team_id["id"])

    home_team_players = home_team_players_data.get("players", [])
    away_team_players = away_team_players_data.get("players", [])

    # if tracker:
    #     await tracker.update(55, "Processing and organizing player data...")

    # Build jersey -> full name maps from Transfermarkt data for both teams
    def build_tm_maps(players_list: List[Dict[str, Any]]):
        jersey_to_fullname = {}
        roster_names = []
        for p in players_list:
            try:
                jersey = str(p.get("jersey_number", "")).strip()
                name = (p.get("name") or "").strip()
                if jersey:
                    jersey_to_fullname[jersey] = name or jersey_to_fullname.get(jersey)
                if name:
                    roster_names.append(name)
            except Exception:
                continue
        return jersey_to_fullname, roster_names

    home_jersey_to_fullname, home_roster_names = build_tm_maps(home_team_players)
    away_jersey_to_fullname, away_roster_names = build_tm_maps(away_team_players)

    print("DEBUG: Skipping FBref stats collection (removed)")

    # Organize players by position for both teams
    home_team_positions = defaultdict(list)
    away_team_positions = defaultdict(list)

    for player in home_team_players:
        home_team_positions[player["position"]].append(player)

    for player in away_team_players:
        away_team_positions[player["position"]].append(player)

    # Process starting lineups
    home_lineup = lineups.get("home_team", {})
    away_lineup = lineups.get("away_team", {})

    # Find players in lineup by jersey number and organize by position
    home_lineup_by_position = defaultdict(list)
    away_lineup_by_position = defaultdict(list)

    for jersey_num, player_name in home_lineup.items():
        # First try to find player by jersey number
        found_player = None
        for player in home_team_players:
            if str(player.get("jersey_number", "")) == jersey_num:
                found_player = player
                break

        if found_player:
            # Player found by jersey number - use their actual position and market value
            home_lineup_by_position[found_player["position"]].append(found_player)
        else:
            # Player not found by jersey number - try to find by name
            name_found_player = None
            for player in home_team_players:
                # Try to match by name (case insensitive, partial match)
                if player.get("name", "").lower() in player_name.lower() or player_name.lower() in player.get("name",
                                                                                                              "").lower():
                    name_found_player = player
                    break

            if name_found_player:
                # Player found by name - use their actual position and market value
                home_lineup_by_position[name_found_player["position"]].append(name_found_player)
            else:
                # Player not found at all - create fallback entry
                home_lineup_by_position["Unknown Position"].append({
                    "name": player_name,
                    "jersey_number": jersey_num,
                    "position": "Unknown Position",
                    "marketValue": "€0",
                    "parsed_market_value": 0
                })

    for jersey_num, player_name in away_lineup.items():
        # First try to find player by jersey number
        found_player = None
        for player in away_team_players:
            if str(player.get("jersey_number", "")) == jersey_num:
                found_player = player
                break

        if found_player:
            # Player found by jersey number - use their actual position and market value
            away_lineup_by_position[found_player["position"]].append(found_player)
        else:
            # Player not found by jersey number - try to find by name
            name_found_player = None
            for player in away_team_players:
                # Try to match by name (case insensitive, partial match)
                if player.get("name", "").lower() in player_name.lower() or player_name.lower() in player.get("name",
                                                                                                              "").lower():
                    name_found_player = player
                    break

            if name_found_player:
                # Player found by name - use their actual position and market value
                away_lineup_by_position[name_found_player["position"]].append(name_found_player)
            else:
                # Player not found at all - create fallback entry
                away_lineup_by_position["Unknown Position"].append({
                    "name": player_name,
                    "jersey_number": jersey_num,
                    "position": "Unknown Position",
                    "marketValue": "€0",
                    "parsed_market_value": 0
                })

    # Process substitutions if provided
    home_sub_by_position = defaultdict(list)
    away_sub_by_position = defaultdict(list)

    if substitutions:
        print(f"DEBUG: Processing substitutions data: {substitutions}")
        home_substitutions = substitutions.get("home_team", {}).get("substitutions", [])
        away_substitutions = substitutions.get("away_team", {}).get("substitutions", [])

        print(f"DEBUG: Home team substitutions: {home_substitutions}")
        print(f"DEBUG: Away team substitutions: {away_substitutions}")
        print(f"DEBUG: Home team name: {club_home_name}")
        print(f"DEBUG: Away team name: {club_away_name}")

        for sub in home_substitutions:
            jersey_num = sub.get("jersey_number", "")
            player_name = sub.get("player_name", "")

            print(f"DEBUG: Processing home substitution - jersey: {jersey_num}, name: {player_name}")

            # First try to find player by jersey number
            found_player = None
            for player in home_team_players:
                if str(player.get("jersey_number", "")) == jersey_num:
                    found_player = player
                    print(
                        f"DEBUG: Found home player by jersey number: {player.get('name')} at position {player.get('position')}")
                    break

            if found_player:
                # Player found by jersey number - use their actual position and market value
                home_sub_by_position[found_player["position"]].append(found_player)
                print(f"DEBUG: Added home player to {found_player['position']} substitutions")
            else:
                # Player not found by jersey number - try to find by name
                name_found_player = None
                for player in home_team_players:
                    # Try to match by name (case insensitive, partial match)
                    if player.get("name", "").lower() in player_name.lower() or player_name.lower() in player.get(
                            "name", "").lower():
                        name_found_player = player
                        print(
                            f"DEBUG: Found home player by name: {player.get('name')} at position {player.get('position')}")
                        break

                if name_found_player:
                    # Player found by name - use their actual position and market value
                    home_sub_by_position[name_found_player["position"]].append(name_found_player)
                    print(f"DEBUG: Added home player by name to {name_found_player['position']} substitutions")
                else:
                    # Player not found at all - create fallback entry
                    home_sub_by_position["Unknown Position"].append({
                        "name": player_name,
                        "jersey_number": jersey_num,
                        "position": "Unknown Position",
                        "marketValue": "€0",
                        "parsed_market_value": 0
                    })
                    print(f"DEBUG: Created fallback entry for home player: {player_name}")

        for sub in away_substitutions:
            jersey_num = sub.get("jersey_number", "")
            player_name = sub.get("player_name", "")

            # First try to find player by jersey number
            found_player = None
            for player in away_team_players:
                if str(player.get("jersey_number", "")) == jersey_num:
                    found_player = player
                    break

            if found_player:
                # Player found by jersey number - use their actual position and market value
                away_sub_by_position[found_player["position"]].append(found_player)
            else:
                # Player not found by jersey number - try to find by name
                name_found_player = None
                for player in away_team_players:
                    # Try to match by name (case insensitive, partial match)
                    if player.get("name", "").lower() in player_name.lower() or player_name.lower() in player.get(
                            "name", "").lower():
                        name_found_player = player
                        break

                if name_found_player:
                    # Player found by name - use their actual position and market value
                    away_sub_by_position[name_found_player["position"]].append(name_found_player)
                else:
                    # Player not found at all - create fallback entry
                    away_sub_by_position["Unknown Position"].append({
                        "name": player_name,
                        "jersey_number": jersey_num,
                        "position": "Unknown Position",
                        "marketValue": "€0",
                        "parsed_market_value": 0
                    })

    # Debug: Show final state of substitution dictionaries
    print(f"DEBUG: Final home_sub_by_position: {dict(home_sub_by_position)}")
    print(f"DEBUG: Final away_sub_by_position: {dict(away_sub_by_position)}")

    async def compare_at_position_one_on_one(pos_key: str, player_type: str = "starting") -> List[Dict[str, Any]]:
        """Compare players at a specific position"""
        home_players = home_lineup_by_position.get(pos_key,
                                                   []) if player_type == "starting" else home_sub_by_position.get(
            pos_key, [])
        away_players = away_lineup_by_position.get(pos_key,
                                                   []) if player_type == "starting" else away_sub_by_position.get(
            pos_key, [])

        comparisons = []

        # Get the maximum number of players to compare
        max_players = max(len(home_players), len(away_players))

        for i in range(max_players):
            home_player = home_players[i] if i < len(home_players) else None
            away_player = away_players[i] if i < len(away_players) else None

            home_market_value = await parse_market_value(home_player.get("marketValue", "€0")) if home_player else 0
            away_market_value = await parse_market_value(away_player.get("marketValue", "€0")) if away_player else 0

            # FBref stats removed - using only Transfermarkt data

            # Determine the result based on player availability and market values
            if home_player and away_player:
                if home_market_value > away_market_value:
                    result = "home_higher"
                elif away_market_value > home_market_value:
                    result = "away_higher"
                else:
                    result = "equal"
            elif home_player and not away_player:
                result = "home_only"
            elif away_player and not home_player:
                result = "away_only"
            else:
                result = "no_players"

            comparison = {
                "position": pos_key,
                "player_type": player_type,
                "home_player": {
                    "name": home_player.get("name", "N/A") if home_player else "N/A",
                    "jersey_number": home_player.get("jersey_number", "N/A") if home_player else "N/A",
                    "market_value": home_market_value,
                    "parsed_market_value": home_market_value
                },
                "away_player": {
                    "name": away_player.get("name", "N/A") if away_player else "N/A",
                    "jersey_number": away_player.get("jersey_number", "N/A") if away_player else "N/A",
                    "market_value": away_market_value,
                    "parsed_market_value": away_market_value
                },
                "difference": home_market_value - away_market_value,
                "result": result
            }

            comparisons.append(comparison)

        return comparisons

    # Compare players at each position
    comparison_results = []

    if tracker:
        await tracker.update(60, "Analyzing starting lineups by position...")

    # Compare starting lineups
    all_positions = set(list(home_lineup_by_position.keys()) + list(away_lineup_by_position.keys()))
    for position in all_positions:
        home_players = home_lineup_by_position.get(position, [])
        away_players = away_lineup_by_position.get(position, [])

        comparison = await compare_at_position_one_on_one(position, "starting")
        comparison_results.extend(comparison)

    # Compare substitutions
    if substitutions:
        # if tracker:
        #     await tracker.update(70, "Analyzing substitution players by position...")

        all_sub_positions = set(list(home_sub_by_position.keys()) + list(away_sub_by_position.keys()))
        for position in all_sub_positions:
            home_players = home_sub_by_position.get(position, [])
            away_players = away_sub_by_position.get(position, [])

            comparison = await compare_at_position_one_on_one(position, "substitution")
            comparison_results.extend(comparison)

    # if tracker:
    #     await tracker.update(80, "Calculating total market values...")

    # Calculate total market values
    home_total = 0
    for players in home_lineup_by_position.values():
        for player in players:
            home_total += await parse_market_value(player.get("marketValue", "€0"))

    away_total = 0
    for players in away_lineup_by_position.values():
        for player in players:
            away_total += await parse_market_value(player.get("marketValue", "€0"))

    # FBref stats summary removed

    # Wait for odds data that started fetching at the beginning
    # odds_data = None
    # try:
    #     print(f"DEBUG: Waiting for odds fetch to complete for {club_home_name} vs {club_away_name}")
    #     odds_data = await odds_task
    #     if odds_data:
    #         print(f"DEBUG: Successfully fetched odds: {odds_data['bookmaker']} odds available")
    #         print(f"DEBUG: Odds data preview: {json.dumps(odds_data, indent=2)}")
    #         print(f"DEBUG: Odds data contains shin_analysis: {'shin_analysis' in odds_data}")
    #         if 'shin_analysis' in odds_data:
    #             print(f"DEBUG: Shin analysis Z value: {odds_data['shin_analysis']['shin_metrics']['z']:.4f}")
    #     else:
    #         print(f"DEBUG: No odds found for {club_home_name} vs {club_away_name}")
    #         print(f"DEBUG: This could be because:")
    #         print(f"DEBUG: 1. No upcoming match between these teams")
    #         print(f"DEBUG: 2. Pinnacle doesn't have odds for this match")
    #         print(f"DEBUG: 3. Match already started (only pre-match odds shown)")
    #         print(f"DEBUG: 4. Team names don't match odds API format")
    # except Exception as e:
    #     print(f"DEBUG: Error fetching odds: {e}")
    #     import traceback
    #     print(f"DEBUG: Full error traceback: {traceback.format_exc()}")

    response = {
        "home_team": club_home_name,
        "away_team": club_away_name,
        "comparison": comparison_results,
        "total_market_values": {
            club_home_name: home_total,
            club_away_name: away_total,
        }
    }

    # # Add odds data if available
    # if odds_data:
    #     response["odds"] = odds_data

    return response


@router.delete("/compare/{home_team}/{away_team}/cache")
async def clear_comparison_cache(home_team: str, away_team: str):
    """Clear the cache for a specific team comparison"""
    try:
        cache_key = f"lineups_substitutions:{home_team}:{away_team}"
        await redis_client.delete(cache_key)
        return {"message": f"Cache cleared for {home_team} vs {away_team}"}
    except Exception as e:
        logging.error(f"ERROR: Failed to clear cache: {type(e).__name__} - {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")


@router.get("/compare/{home_team}/{away_team}/progress")
async def get_comparison_progress(home_team: str, away_team: str):
    progress_key = f"{home_team}_{away_team}"
    logger.debug(f"SSE client connected for key: {progress_key}")

    # Get-or-create a ready event so we can AWAIT it instead of polling
    if progress_key not in _tracker_ready_events:
        _tracker_ready_events[progress_key] = asyncio.Event()

    ready_event = _tracker_ready_events[progress_key]

    # If the tracker already exists (race-free check), mark event set immediately
    if progress_key in progress_tasks:
        ready_event.set()

    async def progress_stream():
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"

            # Wait for the analysis task to register its tracker — no polling
            try:
                await asyncio.wait_for(ready_event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Analysis did not start in time'})}\n\n"
                return

            tracker = progress_tasks[progress_key]
            queue = tracker.subscribe()

            try:
                # Replay current state for late-joining clients
                if tracker.progress > 0:
                    yield f"data: {json.dumps({'type': 'progress', 'progress': tracker.progress, 'stage': tracker.stage})}\n\n"

                if tracker.is_done:
                    # Already finished before we subscribed
                    msg = "complete" if tracker.is_completed else tracker.error_message
                    yield f"data: {json.dumps({'type': 'complete' if tracker.is_completed else 'error', 'message': msg})}\n\n"
                    return

                # Stream live updates
                while not tracker.is_done:
                    try:
                        update = await asyncio.wait_for(queue.get(), timeout=30.0)
                        yield f"data: {json.dumps(update)}\n\n"
                        if update.get("type") in ("complete", "error"):
                            break
                    except asyncio.TimeoutError:
                        yield f"data: {json.dumps({'type': 'keepalive', 'timestamp': datetime.now().isoformat()})}\n\n"

            finally:
                tracker.unsubscribe(queue)
                if tracker.is_done:
                    cleanup_tracker(progress_key)

        except Exception as e:
            logger.error(f"SSE stream error for {progress_key}: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        progress_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )


@router.get("/compare/{home_team}/{away_team}", dependencies=[Depends(auth.has_access)])
async def get_comparaison_result(home_team: str, away_team: str):
    print(f"DEBUG: Starting comparison for {home_team} vs {away_team}")

    # Create progress tracker for this request using simple key
    progress_key = f"{home_team}_{away_team}"
    print(f"DEBUG: Creating progress tracker with key: {progress_key}")

    tracker = ProgressTracker(home_team, away_team)
    register_tracker(progress_key, tracker)

    print(f"DEBUG: Progress tracker created and stored with key: {progress_key}")
    print(f"DEBUG: Total progress trackers: {len(progress_tasks)}")
    print(f"DEBUG: Progress tracker keys: {list(progress_tasks.keys())}")

    try:
        print(f"DEBUG: Updating progress to 5%")
        await tracker.update(5, "Starting analysis...")

        # Check cache first
        cache_key = f"lineups_substitutions:{home_team}:{away_team}"
        cached_result = await redis_client.get(cache_key)

        if cached_result:
            try:
                # Handle both string and bytes from Redis
                if isinstance(cached_result, bytes):
                    cached_result = cached_result.decode('utf-8')
                cached_data = json.loads(cached_result)
                print(f"DEBUG: Returning cached data for {home_team} vs {away_team}")
                await tracker.complete()
                return cached_data
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                print(f"DEBUG: Cache corrupted or invalid: {e}")
                pass  # Continue to fetch fresh data if cache is corrupted

        print(f"DEBUG: Updating progress to 10%")
        await tracker.update(10, "Initializing scraper...")
        print(f"DEBUG: Initializing scraper")
        # Initialize scraper
        scraper = get_scraper(SportType.FOOTBALL, persist_outputs=False)

        print(f"DEBUG: Updating progress to 15%")
        await tracker.update(15, "Searching for team match...")
        print(f"DEBUG: Getting match ID for {home_team}")
        # Get match ID for the home team
        match_id = scraper.get_team_id_by_name(home_team)

        if not match_id:
            print(f"DEBUG: No match ID found for {home_team}")
            await tracker.fail(f"Could not find match ID for team {home_team}")
            raise HTTPException(status_code=404, detail=f"Could not find match ID for team {home_team}")

        print(f"DEBUG: Updating progress to 20%")
        await tracker.update(20, "Found team match, starting data collection...")
        print(f"DEBUG: Found match ID: {match_id}")
        print(f"DEBUG: Scraping lineups and substitutions")

        # Scrape lineups and substitutions
        combined_data_dict = scraper.scrape_lineups_and_substitutions(match_id)

        print(f"DEBUG: Updating progress to 30%")
        await tracker.update(30, "Data collection complete, processing player information...")
        print(f"DEBUG: Extracting lineups and substitutions")
        # Extract lineups and substitutions
        lineups_dict_for_processing = combined_data_dict.get("lineups", {})
        substitutions_dict_for_processing = combined_data_dict.get("substitutions", {})
        print(f"DEBUG: Lineups data extracted: {lineups_dict_for_processing}")
        print(f"DEBUG: Substitutions data extracted: {substitutions_dict_for_processing}")

        print(f"DEBUG: Updating progress to 40%")
        await tracker.update(40, "Starting player comparison analysis...")
        print(f"DEBUG: Comparing players")
        # Compare players
        comparison_result = await compare_players_with_lineup_and_substitutions(
            home_team,
            away_team,
            lineups_dict_for_processing,
            substitutions_dict_for_processing,
            tracker  # Pass the tracker for progress updates
        )

        print(f"DEBUG: Updating progress to 95%")
        await tracker.update(95, "Finalizing results and caching...")
        print(f"DEBUG: Comparison result: {comparison_result}")

        # Cache the result
        await redis_client.setex(cache_key, 3600, json.dumps(comparison_result))  # Cache for 1 hour

        print(f"DEBUG: Marking progress as complete")
        await tracker.complete()
        return comparison_result

    except Exception as e:
        print(f"DEBUG: Exception occurred: {type(e).__name__} - {str(e)}")
        logging.error(f"ERROR: Unhandled Exception in get_comparaison_result: {type(e).__name__} - {str(e)}")
        await tracker.fail(f"Internal server error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    finally:
        # Cleanup progress tracker
        if progress_key in progress_tasks:
            del progress_tasks[progress_key]
            print(f"DEBUG: Progress tracker cleaned up for key: {progress_key}")


@router.get("/{club_id}/profile")
def get_club_profile(club_id: str) -> dict:
    tfmkt = TransfermarktClubProfile(club_id=club_id)
    return tfmkt.get_club_profile()


@router.get("/{club_id}/stadium")
def get_club_stadium(club_id: str) -> dict:
    tfmkt = TransfermarktClubProfile(club_id=club_id)
    return tfmkt.get_club_stadium()


@router.get("/{club_id}/players")
def get_club_players(club_id: str, season_id: Optional[str] = None) -> dict:
    tfmkt = TransfermarktClubPlayers(club_id=club_id, season_id=season_id)
    return tfmkt.get_club_players()


@router.get("/{club_id}/staffs")
def get_club_staffs(club_id: str) -> dict:
    tfmkt = TransfermarktClubStaffs(club_id=club_id)
    return tfmkt.get_club_staffs()
