import re
import time
import logging

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from fuzzywuzzy import fuzz
from urllib.parse import quote

from app.services.flashscore_scraper.flashscore_scraper import FlashScoreScraper

logger = logging.getLogger(__name__)


class TennisFlashScoreScraper(FlashScoreScraper):
    """
    FlashScore scraper specialised for tennis matches.

    Key differences from football:
      - Only 2 outcomes (player 1 win / player 2 win) — no draw
      - Participants are players, not teams (uses /player/ links)
      - Odds comparison page has 2 cells per row instead of 3
    """

    # Tennis player name abbreviations (extend as needed)
    PLAYER_NAME_ABBREVIATIONS = {}

    # ------------------------------------------------------------------ #
    #  Match info                                                         #
    # ------------------------------------------------------------------ #
    def get_match_info(self, match_id: str) -> dict:
        """
        Scrape tennis match metadata: player names and start time.

        The HTML layout for participant names and start time is identical
        to football (duelParticipant__home / __away), so we reuse the same
        XPaths.  The only difference is that the returned dict uses
        ``player1`` / ``player2`` keys instead of ``home_team`` / ``away_team``.

        Returns
        -------
        dict
            {"player1": str, "player2": str,
             "start_time": str|None, "start_time_raw": str|None}
        """
        driver = self._get_driver()

        try:
            url = f"{self.BASE_URL}match/{match_id}/#/match-summary/match-summary"
            self.logger.info("Fetching tennis match info from: %s", url)
            driver.get(url)

            wait = WebDriverWait(driver, 20)
            self._accept_privacy_or_cookies(driver)

            # Player names — same selectors as football
            player1 = self._safe_text(driver, [
                "//div[contains(@class,'duelParticipant__home')]//a[contains(@class,'participant__participantName')]",
                "//div[contains(@class,'duelParticipant__home')]//div[contains(@class,'participant__participantName')]",
            ])

            player2 = self._safe_text(driver, [
                "//div[contains(@class,'duelParticipant__away')]//a[contains(@class,'participant__participantName')]",
                "//div[contains(@class,'duelParticipant__away')]//div[contains(@class,'participant__participantName')]",
            ])

            # Start time — identical to football
            raw_start_time = self._safe_text(driver, [
                "//div[contains(@class,'duelParticipant__startTime')]//div",
                "//div[contains(@class,'startTime')]",
                "//span[contains(@class,'startTime')]",
            ])

            self.logger.info(
                "Raw tennis match info — player1: '%s' | player2: '%s' | start_time: '%s'",
                player1, player2, raw_start_time,
            )

            start_time_utc = self._parse_flashscore_datetime(raw_start_time, match_id)

            return {
                "player1": player1 or "unknown",
                "player2": player2 or "unknown",
                "start_time": start_time_utc,
                "start_time_raw": raw_start_time,
            }

        except Exception as e:
            self.logger.error("Failed to get tennis match info for %s: %s", match_id, e, exc_info=True)
            raise

        finally:
            driver.quit()

    # ------------------------------------------------------------------ #
    #  Odds scraping                                                      #
    # ------------------------------------------------------------------ #
    def get_odds_by_match_id(self, match_id: str) -> dict:
        """
        Scrape 2-way odds for a tennis match.

        Strategy (two tiers):
          1. **Summary page widget** — FlashScore renders a small ``div.odds``
             widget directly on the match-summary page with 2 buttons
             (``wcl-oddsCell``) each containing a ``span[data-testid=wcl-oddsValue]``.
             This is the most reliable source for tennis.
          2. **Odds-comparison tab** — Fall back to the dedicated odds page
             (same approach as football) if the summary widget is absent.

        Returns
        -------
        dict
            {"player1": float|None, "player2": float|None,
             "bookmaker": str|None, "source_url": str}
        """
        self.logger.info("Scraping tennis odds for match_id: %s", match_id)
        driver = self._get_driver()

        try:
            summary_url = f"{self.BASE_URL}match/{match_id}/#/match-summary/match-summary"
            self.logger.info("Navigating to match summary: %s", summary_url)
            driver.get(summary_url)

            wait = WebDriverWait(driver, 20)
            self._accept_privacy_or_cookies(driver)

            # Wait for the page to load (participant names are a good signal)
            try:
                wait.until(EC.presence_of_element_located((
                    By.XPATH,
                    "//div[contains(@class,'duelParticipant')]"
                )))
            except TimeoutException:
                self.logger.warning("Match page did not load for %s", match_id)

            time.sleep(2)

            # ==============================================================
            # Tier 1: Odds widget on the match summary page
            # ==============================================================
            result = self._try_summary_page_odds(driver, match_id)
            if result:
                return result

            # ==============================================================
            # Tier 2: Odds-comparison tab (fallback)
            # ==============================================================
            self.logger.info("Summary odds not found, trying odds-comparison tab...")
            result = self._try_odds_comparison_tab(driver, wait, match_id)
            if result:
                return result

            self.logger.warning("No valid odds found for tennis match %s via any method", match_id)
            return {
                "player1": None, "player2": None,
                "bookmaker": None, "source_url": driver.current_url,
            }

        except Exception as e:
            self.logger.error("Error scraping tennis odds for match_id '%s': %s", match_id, e, exc_info=True)
            raise

        finally:
            driver.quit()

    def _try_summary_page_odds(self, driver, match_id: str) -> dict | None:
        """
        Try to extract odds from the summary page's ``div.odds`` widget.

        HTML structure (from FlashScore tennis pages):
          <div class="odds">
            <div class="wcl-bookmakerLogo_...">
              <a ...><img alt="Stake.com" class="wcl-logoImage_..." ...></a>
            </div>
            <div class="wclOddsRow">
              <button class="wcl-oddsCell_...">
                <span ... data-testid="wcl-oddsValue">3.15</span>
              </button>
              <button class="wcl-oddsCell_...">
                <span ... data-testid="wcl-oddsValue">1.38</span>
              </button>
            </div>
          </div>

        Returns dict on success, None if widget not found.
        """
        # Multiple selector strategies for the odds container
        odds_container_xpaths = [
            "//div[contains(@class,'odds')]",
            "//div[contains(@class,'wclOddsRow')]",
        ]

        odds_container = None
        for xpath in odds_container_xpaths:
            try:
                odds_container = driver.find_element(By.XPATH, xpath)
                if odds_container:
                    break
            except NoSuchElementException:
                continue

        if not odds_container:
            self.logger.info("No odds widget found on summary page for %s", match_id)
            return None

        # Extract odds values from the widget
        odds_value_selectors = [
            ".//span[@data-testid='wcl-oddsValue']",
            ".//span[contains(@class,'wcl-oddsValue')]",
        ]

        odds_values = []
        for selector in odds_value_selectors:
            try:
                elements = driver.find_elements(By.XPATH, selector)
                for el in elements:
                    text = el.text.strip()
                    if text and self._is_valid_odd(text):
                        odds_values.append(text)
                if len(odds_values) >= 2:
                    break
            except Exception:
                continue

        self.logger.info("Summary page odds values found: %s", odds_values)

        if len(odds_values) < 2:
            self.logger.info("Not enough valid odds on summary page (%d found)", len(odds_values))
            return None

        # Extract bookmaker name
        bookmaker = "Unknown"
        bookmaker_selectors = [
            "//div[contains(@class,'odds')]//img[contains(@class,'wcl-logoImage')]",
            "//div[contains(@class,'odds')]//img[contains(@class,'logoImage')]",
            "//img[contains(@class,'wcl-logoImage')]",
        ]
        for selector in bookmaker_selectors:
            try:
                img = driver.find_element(By.XPATH, selector)
                alt = img.get_attribute("alt")
                if alt:
                    bookmaker = alt
                    break
            except NoSuchElementException:
                continue

        result = {
            "player1": float(odds_values[0]),
            "player2": float(odds_values[1]),
            "bookmaker": bookmaker,
            "source_url": driver.current_url,
        }
        self.logger.info(
            "Tennis odds (summary widget) — player1: %s | player2: %s | bookmaker: %s",
            odds_values[0], odds_values[1], bookmaker,
        )
        return result

    def _try_odds_comparison_tab(self, driver, wait, match_id: str) -> dict | None:
        """
        Fall back to the dedicated odds-comparison tab.
        Returns dict on success, None if odds not found.
        """
        odds_tab_xpaths = [
            "//a[contains(@href, '/odds-comparison/') and contains(@href, 'summary')]",
            "//a[contains(@href, 'odds-comparison')]",
            "//button[normalize-space(text())='Odds']",
            "//a[normalize-space(text())='Odds']",
        ]

        tab_clicked = False
        for i, xpath in enumerate(odds_tab_xpaths):
            try:
                tab = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tab)
                time.sleep(0.5)
                try:
                    tab.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", tab)
                self.logger.info("Clicked odds tab via XPath %d.", i + 1)
                tab_clicked = True
                break
            except TimeoutException:
                self.logger.debug("Odds tab XPath %d timed out.", i + 1)

        if not tab_clicked:
            self.logger.warning("Could not find odds-comparison tab for tennis match %s", match_id)
            return None

        time.sleep(2)

        # ---- Primary selectors (analytics-element based) ----
        ROW_XPATH = "//div[contains(@class,'ui-table__row')]"
        P1_ODD_XPATH = ".//a[contains(@data-analytics-element,'ODD_CELL_1')]//span"
        P2_ODD_XPATH = ".//a[contains(@data-analytics-element,'ODD_CELL_2')]//span"
        BOOKMAKER_XPATH = ".//img[contains(@class,'wcl-logoImage')]"

        # ---- Fallback selectors (button / span based) ----
        P1_ODD_FALLBACK = ".//button[contains(@class,'wcl-oddsCell')][1]//span[contains(@class,'wcl-oddsValue')]"
        P2_ODD_FALLBACK = ".//button[contains(@class,'wcl-oddsCell')][2]//span[contains(@class,'wcl-oddsValue')]"

        try:
            wait.until(EC.presence_of_element_located((By.XPATH, ROW_XPATH)))
        except TimeoutException:
            self.logger.warning("Odds table not found on comparison tab for match %s", match_id)
            return None

        rows = driver.find_elements(By.XPATH, ROW_XPATH)
        self.logger.info("Found %d odds rows on comparison tab.", len(rows))

        for row_idx, row in enumerate(rows):
            p1_text = self._try_element_text(row, [P1_ODD_XPATH, P1_ODD_FALLBACK])
            p2_text = self._try_element_text(row, [P2_ODD_XPATH, P2_ODD_FALLBACK])

            if not p1_text or not p2_text:
                continue

            if not (self._is_valid_odd(p1_text) and self._is_valid_odd(p2_text)):
                self.logger.debug("Row %d skipped — invalid odds.", row_idx)
                continue

            try:
                bookmaker = row.find_element(By.XPATH, BOOKMAKER_XPATH).get_attribute("alt")
            except NoSuchElementException:
                bookmaker = "Unknown"

            result = {
                "player1": float(p1_text),
                "player2": float(p2_text),
                "bookmaker": bookmaker,
                "source_url": driver.current_url,
            }
            self.logger.info(
                "Tennis odds (comparison tab) — player1: %s | player2: %s | bookmaker: %s",
                p1_text, p2_text, bookmaker,
            )
            return result

        self.logger.warning("No valid odds row found on comparison tab for match %s", match_id)
        return None

    # ------------------------------------------------------------------ #
    #  Player name → match ID resolution                                  #
    # ------------------------------------------------------------------ #
    def get_player_id_by_name(self, player_name: str) -> str:
        """
        Resolve a FlashScore match ID from a tennis player name.

        The strategy mirrors football's ``get_team_id_by_name`` but
        searches for ``/player/`` links instead of ``/team/`` links.

        Parameters
        ----------
        player_name : str
            e.g. ``"Djokovic"`` or ``"Sinner Jannik"``

        Returns
        -------
        str
            FlashScore match ID (e.g. ``"rZZxxAIF"``)
        """
        self.logger.info("Resolving tennis match ID for player: %s", player_name)
        driver = self._get_driver()

        try:
            normalized = player_name.strip().lower()

            # ---- Strategy 1: Search page → player page → match ID ----
            search_url = f"{self.BASE_URL}search/?q={quote(normalized)}"
            self.logger.info("Navigating to search URL: %s", search_url)
            driver.get(search_url)

            try:
                self._accept_privacy_or_cookies(driver)
            except Exception:
                pass

            wait = WebDriverWait(driver, 20)

            # Look for /player/ links in the search results
            try:
                player_links = wait.until(EC.presence_of_all_elements_located((
                    By.XPATH,
                    "//a[contains(@href, '/player/')][normalize-space(string())!='']"
                )))
            except TimeoutException:
                player_links = []

            if player_links:
                # Fuzzy-match player name
                best_link = None
                best_score = -1
                for link in player_links:
                    try:
                        text = (link.text or "").strip().lower()
                        if not text:
                            continue
                        score = fuzz.token_set_ratio(text, normalized)
                        if score > best_score:
                            best_score = score
                            best_link = link
                    except Exception:
                        continue

                if best_link and best_score >= 50:
                    self.logger.info("Best player link match (score %d): %s", best_score, best_link.text)
                    try:
                        best_link.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", best_link)

                    wait.until(EC.url_contains("/player/"))
                    time.sleep(1.5)

                    # Player page lists upcoming/recent matches as divs with id g_X_YYYYYY
                    match_divs = wait.until(
                        EC.presence_of_all_elements_located((By.XPATH, "//div[starts-with(@id, 'g_')]"))
                    )

                    for div in match_divs:
                        mid_attr = div.get_attribute("id")
                        parsed = re.sub(r'^g_\d+_', '', mid_attr)
                        if parsed and parsed != mid_attr:
                            self.logger.info("Extracted tennis match ID from player page: %s", parsed)
                            return parsed

            # ---- Strategy 2: Header search UI flow ----
            self.logger.info("Attempting header search UI flow for player: %s", player_name)
            driver.get(self.BASE_URL)
            try:
                self._accept_privacy_or_cookies(driver)
            except Exception:
                pass

            wait = WebDriverWait(driver, 20)

            input_field = None
            try:
                input_field = wait.until(EC.presence_of_element_located((
                    By.XPATH,
                    "//input[@type='text' and contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'search')]"
                )))
            except Exception:
                try:
                    search_button = wait.until(EC.element_to_be_clickable((
                        By.XPATH,
                        "//button[contains(@aria-label,'Search') or contains(@aria-label,'search')]"
                    )))
                    search_button.click()
                    input_field = wait.until(EC.presence_of_element_located((
                        By.XPATH,
                        "//input[@type='text' and contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'search')]"
                    )))
                except Exception as e_open:
                    raise Exception(f"Could not open search input: {e_open}")

            if not input_field:
                raise Exception("Search input not found")

            input_field.clear()
            input_field.send_keys(normalized)
            time.sleep(0.5)

            # Look for /player/ links in the dropdown
            try:
                player_links = wait.until(EC.presence_of_all_elements_located((
                    By.XPATH,
                    "(//a[contains(@href, '/player/')])[position()<=10]"
                )))
            except TimeoutException:
                player_links = []

            best_link = None
            best_score = -1
            for link in player_links:
                try:
                    text = (link.text or "").strip().lower()
                    if not text:
                        continue
                    score = fuzz.token_set_ratio(text, normalized)
                    if score > best_score:
                        best_score = score
                        best_link = link
                except Exception:
                    continue

            if not best_link:
                self._save_debug_screenshot(driver, f"error_header_search_no_player_{player_name.replace(' ', '_')}.png")
                raise Exception(f"Player not found via header search: {player_name}")

            try:
                best_link.click()
            except Exception:
                driver.execute_script("arguments[0].click();", best_link)

            wait.until(EC.url_contains("/player/"))
            time.sleep(1.0)

            match_divs = wait.until(
                EC.presence_of_all_elements_located((By.XPATH, "//div[starts-with(@id, 'g_')]"))
            )
            for div in match_divs:
                mid_attr = div.get_attribute("id")
                parsed = re.sub(r'^g_\d+_', '', mid_attr)
                if parsed and parsed != mid_attr:
                    self.logger.info("Extracted tennis match ID from header search: %s", parsed)
                    return parsed

            self._save_debug_screenshot(driver, f"error_header_search_no_matches_{player_name.replace(' ', '_')}.png")
            raise Exception(f"No upcoming matches found for player {player_name}")

        except Exception as e:
            self.logger.error("Failed to get match ID for player '%s': %s", player_name, e, exc_info=True)
            self._save_debug_screenshot(driver, f"error_get_player_id_{player_name.replace(' ', '_')}.png")
            raise Exception(f"Failed to get match ID for player {player_name}: {e}")

        finally:
            if driver:
                driver.quit()

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #
    def _try_element_text(self, parent, xpaths: list[str]) -> str | None:
        """Try each XPath on *parent*, return first non-empty text found."""
        for xpath in xpaths:
            try:
                el = parent.find_element(By.XPATH, xpath)
                text = el.text.strip()
                if text:
                    return text
            except NoSuchElementException:
                continue
        return None
