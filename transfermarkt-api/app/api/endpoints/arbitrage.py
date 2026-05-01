# api_logic.py
"""Core logic and FastAPI router for finding sports betting arbitrage opportunities."""
from typing import Iterable, Generator, List, Dict, Any, Set, Optional
import time
import requests
from itertools import chain  # Not strictly used after refactor of get_all_odds_data but kept for potential future use
import os
# from dotenv import load_dotenv # load_dotenv is called in shared_dependencies
from enum import Enum

from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import get_current_user
from app.core.shared_dependencies import get_configured_api_key
from app.models.users import User

# Attempt to import tqdm, but make it optional
try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda iterable, *args, **kwargs: iterable

# --- Constants ---
BASE_URL = "api.the-odds-api.com/v4"
PROTOCOL = "https://"


# --- Custom Exceptions ---
class APIException(RuntimeError):
    """Custom exception for API related errors."""

    def __init__(self, message: str, response: requests.Response = None):
        super().__init__(message)
        self.response_content = response.json() if response and response.content else None
        self.status_code = response.status_code if response else None

    def __str__(self):
        if self.response_content and 'message' in self.response_content:
            return f"('{self.args[0]}', '{self.response_content['message']}')"
        return f"('{self.args[0]}')"


class AuthenticationException(APIException):
    """Exception for authentication failures with The Odds API."""
    pass


class RateLimitException(APIException):
    """Exception for when API rate limits are exceeded."""
    pass


# --- Core Logic Functions ---
def handle_faulty_response(response: requests.Response):
    if response.status_code == 401:
        raise AuthenticationException("Failed to authenticate with the API. Is the API key valid?", response)
    elif response.status_code == 429:
        raise RateLimitException("Encountered API rate limit.", response)
    else:
        raise APIException(f"Unknown issue arose while trying to access the API. Status: {response.status_code}",
                           response)


def get_sports(key: str) -> Set[str]:
    """Fetches the list of available sports from The Odds API."""
    url = f"{BASE_URL}/sports/"
    escaped_url = PROTOCOL + url
    # Debug: API key loaded successfully
    querystring = {"apiKey": key}
    try:
        response = requests.get(escaped_url, params=querystring, timeout=10)
        response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
    except requests.exceptions.HTTPError:
        # Pass the original response object to handle_faulty_response
        handle_faulty_response(response)
    except requests.exceptions.RequestException as req_err:  # Catches other errors like connection, timeout
        raise APIException(f"Request failed: {req_err}")
    try:
        return {item["key"] for item in response.json()}
    except (ValueError, KeyError) as e:  # Catches JSON decoding errors or if "key" is missing
        raise APIException(f"Failed to parse sports data from API: {e}", response)


def get_data_for_sport(key: str, sport: str, region: str = "eu") -> List[Dict[str, Any]]:
    """Fetches odds data for a specific sport and region."""
    url = f"{BASE_URL}/sports/{sport}/odds/"
    escaped_url = PROTOCOL + url
    querystring = {"apiKey": key, "regions": region, "oddsFormat": "decimal", "dateFormat": "unix"}
    try:
        response = requests.get(escaped_url, params=querystring, timeout=15)
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        handle_faulty_response(response)
    except requests.exceptions.RequestException as req_err:
        raise APIException(f"Request failed for sport {sport}: {req_err}")
    try:
        data = response.json()
        if isinstance(data, str):  # API might return a message string
            print(f"API returned a message for sport {sport}, region {region}: {data}")
            return []
        if not isinstance(data, list):  # Expected data is a list of matches
            raise APIException(f"Unexpected data format received for sport {sport}: {type(data)}", response)
        return data
    except ValueError as e:  # JSON decoding error
        raise APIException(f"Failed to parse odds data for sport {sport}: {e}", response)


def process_match_data(matches: Iterable[Dict[str, Any]], include_started_matches: bool = True) -> Generator[
    Dict[str, Any], None, None]:
    """Extracts relevant information from matches and calculates implied odds."""
    processed_matches_iterable = tqdm(matches, desc="Processing matches", leave=False, unit=" matches") if tqdm != (
        lambda iterable, *args, **kwargs: iterable) and matches else matches
    for match in processed_matches_iterable:
        try:
            start_time = int(match["commence_time"])
            if not include_started_matches and start_time < time.time():
                continue
            best_odd_per_outcome = {}
            if not match.get("bookmakers") or not isinstance(match["bookmakers"], list):
                continue  # Skip match if no bookmakers or invalid format
            for bookmaker in match["bookmakers"]:
                bookie_name = bookmaker.get("title", "Unknown Bookmaker")
                if not bookmaker.get("markets") or not isinstance(bookmaker["markets"], list) or not bookmaker[
                    "markets"]:
                    continue  # Skip bookmaker if no markets or invalid format

                market = bookmaker["markets"][0]  # Assuming H2H market is always first
                if not market.get("outcomes") or not isinstance(market["outcomes"], list):
                    continue  # Skip market if no outcomes or invalid format

                for outcome in market["outcomes"]:
                    outcome_name = outcome.get("name")
                    odd_price = outcome.get("price")
                    if outcome_name is None or odd_price is None:
                        continue  # Skip outcome if missing name or price
                    try:
                        odd = float(odd_price)
                    except ValueError:
                        continue  # Skip outcome if price is not a valid float
                    if outcome_name not in best_odd_per_outcome or odd > best_odd_per_outcome[outcome_name][1]:
                        best_odd_per_outcome[outcome_name] = (bookie_name, odd)

            if not best_odd_per_outcome or len(best_odd_per_outcome) < 2:  # Need at least two outcomes for arbitrage
                continue

            total_implied_odds = sum(
                1 / details[1] for details in best_odd_per_outcome.values() if details[1] > 0)  # Ensure odd > 0

            # Handle different types of betting markets
            home_team = match.get('home_team')
            away_team = match.get('away_team')
            
            if home_team and away_team:
                # Traditional head-to-head match
                match_name = f"{home_team} vs. {away_team}"
            elif match.get('sport_title') and match.get('description'):
                # Futures/outright markets (like Super Bowl winner)
                match_name = f"{match.get('sport_title')} - {match.get('description')}"
            elif match.get('sport_title'):
                # Fallback to sport title
                match_name = f"{match.get('sport_title')} Event"
            else:
                # Last resort
                match_name = "Unknown Event"

            time_to_start_hours = (start_time - time.time()) / 3600

            yield {
                "match_id": match.get("id", "N/A"),
                "match_name": match_name,
                "match_start_time_unix": start_time,
                "match_start_time_iso": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(start_time)),
                "hours_to_start": round(time_to_start_hours, 2),
                "sport_key": match.get("sport_key", "N/A"),
                "sport_title": match.get("sport_title", "N/A"),
                "best_outcome_odds": best_odd_per_outcome,
                "total_implied_odds": round(total_implied_odds, 5),
            }
        except KeyError as e:
            # print(f"Skipping a match due to missing key: {e} in match data: {match.get('id', 'Unknown ID')}")
            continue  # Skip this match if essential data is missing
        except Exception as e:  # Catch any other unexpected error during match processing
            # print(f"An unexpected error occurred while processing match {match.get('id', 'Unknown ID')}: {e}")
            continue


def get_all_odds_data(api_key: str, sports_keys: Set[str], region: str) -> List[Dict[str, Any]]:
    """Fetches and combines odds data for all specified sports."""
    all_matches_data = []
    # tqdm wrapper for iterating over sports_keys
    sports_iterable = tqdm(list(sports_keys), desc="Fetching data for sports", unit="sport") if tqdm != (
        lambda iterable, *args, **kwargs: iterable) and sports_keys else sports_keys

    for sport_key in sports_iterable:
        try:
            # print(f"Fetching data for sport: {sport_key} in region: {region}")
            sport_data = get_data_for_sport(api_key, sport_key, region=region)
            all_matches_data.extend(sport_data)
        except APIException as e:
            # Log the error and continue with other sports
            print(f"Could not fetch data for sport {sport_key}: {e}")
        except Exception as e:  # Catch any other unexpected error
            print(f"An unexpected error occurred while fetching data for sport {sport_key}: {e}")

    return [item for item in all_matches_data if isinstance(item, dict)]  # Ensure all items are dicts


def find_arbitrage_opportunities_logic(
        api_key: str,
        region: str,
        profit_margin_cutoff: float,
        sports_to_check: Optional[Set[str]] = None,
        include_started: bool = False
) -> List[Dict[str, Any]]:
    """
    Main logic function to find arbitrage opportunities.
    """
    if not api_key:
        # This should ideally be caught by the dependency if called from an endpoint
        raise ValueError("API key is required for find_arbitrage_opportunities_logic.")

    # Server-side logging for the operation
    print(f"Logic: Starting arbitrage search for region: {region}, cutoff: {profit_margin_cutoff * 100:.2f}%")

    sports_to_use: Set[str]
    if sports_to_check is None or not sports_to_check:
        try:
            print("Logic: Fetching available sports...")
            available_sports = get_sports(key=api_key)
            if not available_sports:
                print("Logic: No sports found or API key issue.")
                return []
            print(f"Logic: Found {len(available_sports)} sports: {available_sports}")
            sports_to_use = available_sports
        except APIException as e:
            print(f"Logic: Error fetching sports: {e}")
            raise  # Re-raise to be handled by the endpoint
    else:
        sports_to_use = sports_to_check
        print(f"Logic: Using provided sports list: {sports_to_use}")

    print("Logic: Fetching all odds data...")
    all_odds_data = get_all_odds_data(api_key, sports_to_use, region)

    if not all_odds_data:
        print("Logic: No odds data fetched. Exiting.")
        return []
    print(f"Logic: Total matches/events fetched: {len(all_odds_data)}")

    print("Logic: Processing fetched data to identify opportunities...")
    processed_results = process_match_data(all_odds_data, include_started_matches=include_started)

    arbitrage_opportunities = [
        arb for arb in processed_results
        if 0 < arb["total_implied_odds"] < (1.0 - profit_margin_cutoff)
    ]
    print(f"Logic: Found {len(arbitrage_opportunities)} arbitrage opportunities meeting the criteria.")
    return arbitrage_opportunities


# --- FastAPI Router Definition ---
router = APIRouter()


# --- Pydantic Models for Arbitrage Router ---
class ArbitrageOpportunityModel(BaseModel):
    match_id: str
    match_name: str
    match_start_time_unix: int
    match_start_time_iso: str
    hours_to_start: float
    sport_key: str
    sport_title: str
    best_outcome_odds: Dict[str, List[Any]]  # e.g. {"Team A": ["BookieName", 2.10]}
    total_implied_odds: float
    profit_margin_percentage: float = Field(...,
                                            description="Calculated profit margin as a percentage (e.g., 1.5 for 1.5%)")


class ArbitrageResponseModel(BaseModel):
    message: str
    opportunities_count: int
    opportunities: List[ArbitrageOpportunityModel]


class RegionModel(str, Enum):
    eu = "eu"
    us = "us"
    au = "au"
    uk = "uk"


# --- Arbitrage Endpoints ---
@router.get(
    "/",
    summary="Find Arbitrage Opportunities",
    response_model=ArbitrageResponseModel,
    tags=["Arbitrage Operations"]
)
async def find_arbitrage_endpoint(
        api_key: str = Depends(get_configured_api_key),
        user: User = Depends(get_current_user),
        region: RegionModel = Query(RegionModel.eu, description="The region to search for odds (eu, us, au, uk)."),
        cutoff: float = Query(0.0, ge=0.0, lt=1.0,
                              description="Minimum profit margin cutoff (e.g., 0.01 for 1%). Opportunities with implied odds < (1 - cutoff) will be returned."),
        sports: Optional[str] = Query(None,
                                      description="Comma-separated list of sport keys to check (e.g., 'soccer_epl,basketball_nba'). If not provided, all available sports are checked."),
        include_started_matches: bool = Query(False,
                                              description="Whether to include matches that have already started.")
):
    """
    Identifies sports betting arbitrage opportunities based on the provided parameters.
    Requires server-side ODDS_API_KEY configuration.
    """
    try:
        sports_set: Optional[Set[str]] = set(
            s.strip() for s in sports.split(',')) if sports and sports.strip() else None

        raw_opportunities = find_arbitrage_opportunities_logic(
            api_key=api_key,
            region=region.value,
            profit_margin_cutoff=cutoff,
            sports_to_check=sports_set,
            include_started=include_started_matches
        )

        formatted_opportunities = []
        for opp in raw_opportunities:
            # Ensure total_implied_odds is positive to avoid issues with log or division by zero if that were ever relevant
            if opp.get("total_implied_odds", 0) > 0:
                profit_margin = (1.0 - opp["total_implied_odds"]) * 100
            else:  # Should not happen given the filter in find_arbitrage_opportunities_logic, but defensive
                profit_margin = -float('inf')  # Or some other indicator of invalid data

            formatted_opportunities.append(
                ArbitrageOpportunityModel(
                    **opp,
                    profit_margin_percentage=round(profit_margin, 2)
                )
            )

        count = len(formatted_opportunities)
        message = f"{count} arbitrage opportunities found." if count > 0 else "No arbitrage opportunities found matching your criteria."

        return ArbitrageResponseModel(
            message=message,
            opportunities_count=count,
            opportunities=formatted_opportunities
        )
    except AuthenticationException as e:
        raise HTTPException(status_code=401, detail={"type": "AuthenticationError",
                                                     "message": "Failed to authenticate with The Odds API using the configured API key.",
                                                     "details": e.response_content})
    except RateLimitException as e:
        raise HTTPException(status_code=429,
                            detail={"type": "RateLimitError", "message": str(e), "details": e.response_content})
    except APIException as e:
        status_code = e.status_code if e.status_code and e.status_code >= 400 else 502
        raise HTTPException(status_code=status_code,
                            detail={"type": "UpstreamAPIError", "message": str(e), "details": e.response_content})
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"type": "ValueError", "message": str(e)})
    except Exception as e:  # Catch-all for unexpected errors
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail={"type": "InternalServerError",
                                                     "message": "An unexpected error occurred on the server."})


@router.get(
    "/sports",
    summary="Get Available Sports",
    description="Fetches the list of available sports keys from The Odds API. Requires server-side ODDS_API_KEY configuration.",
    tags=["Arbitrage Operations"]
)
async def list_available_sports_endpoint(
        api_key: str = Depends(get_configured_api_key),
        user: User = Depends(get_current_user),
):
    """
    Endpoint to retrieve all available sports that can be used to find odds.
    """
    try:
        sports_keys = get_sports(key=api_key)
        return {"available_sport_keys": list(sports_keys)}  # Convert set to list for JSON response
    except AuthenticationException as e:
        raise HTTPException(status_code=401, detail={"type": "AuthenticationError",
                                                     "message": "Failed to authenticate with The Odds API using the configured API key.",
                                                     "details": e.response_content})
    except RateLimitException as e:
        raise HTTPException(status_code=429,
                            detail={"type": "RateLimitError", "message": str(e), "details": e.response_content})
    except APIException as e:
        status_code = e.status_code if e.status_code and e.status_code >= 400 else 502
        raise HTTPException(status_code=status_code,
                            detail={"type": "APIGatewayError", "message": str(e), "details": e.response_content})
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail={"type": "InternalServerError",
                                                     "message": f"An unexpected error occurred: {str(e)}"})
