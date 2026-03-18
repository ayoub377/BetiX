import os

from app.models.sport import SportType

SCRAPER_SERVICE_URL = os.environ.get("SCRAPER_SERVICE_URL")
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")


def get_scraper(sport: SportType, **kwargs):
    """Factory function to get the appropriate scraper for a sport.

    When SCRAPER_SERVICE_URL is set (production on Cloud Run), returns a remote
    HTTP client. Otherwise returns a local Chrome-based scraper (local dev).
    """
    if SCRAPER_SERVICE_URL:
        from app.services.flashscore_scraper.scraper_client import (
            RemoteFlashScoreScraper,
            RemoteTennisFlashScoreScraper,
        )
        if sport == SportType.TENNIS:
            return RemoteTennisFlashScoreScraper(SCRAPER_SERVICE_URL, SCRAPER_API_KEY)
        return RemoteFlashScoreScraper(SCRAPER_SERVICE_URL, SCRAPER_API_KEY, sport=sport.value)

    # Local dev — import Chrome-based scrapers (requires Selenium)
    from app.services.flashscore_scraper.flashscore_scraper import FlashScoreScraper
    from app.services.flashscore_scraper.tennis_scraper import TennisFlashScoreScraper

    _registry = {
        SportType.FOOTBALL: FlashScoreScraper,
        SportType.TENNIS: TennisFlashScoreScraper,
    }
    cls = _registry.get(sport)
    if not cls:
        raise ValueError(f"No scraper registered for sport: {sport}")
    return cls(**kwargs)
