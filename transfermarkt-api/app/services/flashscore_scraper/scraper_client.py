"""
Remote scraper client — drop-in replacement for FlashScoreScraper / TennisFlashScoreScraper.
Delegates scraping to the scraper microservice running on the GCE VM via HTTP.
"""
import logging

import requests

logger = logging.getLogger(__name__)


class RemoteFlashScoreScraper:
    """Calls the scraper microservice instead of running Chrome locally."""

    def __init__(self, base_url: str, api_key: str = "", sport: str = "football", **kwargs):
        self.base_url = base_url.rstrip("/")
        self.sport = sport
        self.session = requests.Session()
        self.session.headers["X-Scraper-Key"] = api_key
        self.logger = logging.getLogger(self.__class__.__name__)

    def get_odds_by_match_id(self, match_id: str) -> dict:
        resp = self.session.get(
            f"{self.base_url}/scrape/odds/{match_id}",
            params={"sport": self.sport},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def get_match_info(self, match_id: str) -> dict:
        resp = self.session.get(
            f"{self.base_url}/scrape/match-info/{match_id}",
            params={"sport": self.sport},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def get_team_id_by_name(self, team_name: str) -> str:
        resp = self.session.get(
            f"{self.base_url}/scrape/team-id/{team_name}",
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["match_id"]

    def scrape_lineups_and_substitutions(self, match_id: str) -> dict:
        resp = self.session.get(
            f"{self.base_url}/scrape/lineups/{match_id}",
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()


class RemoteTennisFlashScoreScraper(RemoteFlashScoreScraper):
    """Remote client for tennis scraping."""

    def __init__(self, base_url: str, api_key: str = "", **kwargs):
        super().__init__(base_url, api_key, sport="tennis", **kwargs)

    def get_player_id_by_name(self, player_name: str) -> str:
        resp = self.session.get(
            f"{self.base_url}/scrape/player-id/{player_name}",
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["match_id"]
