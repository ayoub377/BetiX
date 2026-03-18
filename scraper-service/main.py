"""
Scraper microservice — runs on GCE VM, exposes FlashScore scraping via HTTP.
Cloud Run calls this instead of running Chrome locally.
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Header

from app.models.sport import SportType
from app.services.flashscore_scraper.flashscore_scraper import FlashScoreScraper
from app.services.flashscore_scraper.tennis_scraper import TennisFlashScoreScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Scraper Service")

SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")

scrapers = {
    SportType.FOOTBALL: FlashScoreScraper(persist_outputs=False),
    SportType.TENNIS: TennisFlashScoreScraper(persist_outputs=False),
}

executor = ThreadPoolExecutor(max_workers=2)


def _get_scraper(sport: str):
    try:
        sport_type = SportType(sport)
    except ValueError:
        sport_type = SportType.FOOTBALL
    return scrapers.get(sport_type, scrapers[SportType.FOOTBALL])


def _check_key(key: str):
    if SCRAPER_API_KEY and key != SCRAPER_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/scrape/odds/{match_id}")
async def scrape_odds(match_id: str, sport: str = "football", x_scraper_key: str = Header("")):
    _check_key(x_scraper_key)
    scraper = _get_scraper(sport)
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(executor, scraper.get_odds_by_match_id, match_id)
        return result
    except Exception as e:
        logger.error("Scrape odds failed for %s: %s", match_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/scrape/match-info/{match_id}")
async def scrape_match_info(match_id: str, sport: str = "football", x_scraper_key: str = Header("")):
    _check_key(x_scraper_key)
    scraper = _get_scraper(sport)
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(executor, scraper.get_match_info, match_id)
        return result
    except Exception as e:
        logger.error("Scrape match-info failed for %s: %s", match_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/scrape/team-id/{team_name}")
async def scrape_team_id(team_name: str, x_scraper_key: str = Header("")):
    _check_key(x_scraper_key)
    scraper = scrapers[SportType.FOOTBALL]
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        match_id = await loop.run_in_executor(executor, scraper.get_team_id_by_name, team_name)
        return {"match_id": match_id}
    except Exception as e:
        logger.error("Team ID resolution failed for %s: %s", team_name, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/scrape/player-id/{player_name}")
async def scrape_player_id(player_name: str, x_scraper_key: str = Header("")):
    _check_key(x_scraper_key)
    scraper = scrapers[SportType.TENNIS]
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        match_id = await loop.run_in_executor(executor, scraper.get_player_id_by_name, player_name)
        return {"match_id": match_id}
    except Exception as e:
        logger.error("Player ID resolution failed for %s: %s", player_name, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/scrape/lineups/{match_id}")
async def scrape_lineups(match_id: str, x_scraper_key: str = Header("")):
    _check_key(x_scraper_key)
    scraper = scrapers[SportType.FOOTBALL]
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(executor, scraper.scrape_lineups_and_substitutions, match_id)
        return result
    except Exception as e:
        logger.error("Lineups scrape failed for %s: %s", match_id, e)
        raise HTTPException(status_code=500, detail=str(e))
