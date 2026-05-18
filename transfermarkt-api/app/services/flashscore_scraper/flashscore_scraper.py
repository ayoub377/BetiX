import re
import time
import logging
import json
import subprocess
import signal
from datetime import datetime
from pathlib import Path  # For creating an output directory if needed

import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from fuzzywuzzy import fuzz, process
from urllib.parse import quote


# Placeholder for your utility function
def extract_first_name(full_name):
    return full_name.split(' ')[0] if full_name and ' ' in full_name else full_name  # একটু উন্নত করা হলো


# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        # logging.FileHandler("scraper.log") # Optional: Log to a file
    ]
)


class FlashScoreScraper:
    TEAM_NAME_ABBREVIATIONS = {
        # Common abbreviations and site-localized variants
        "atletico madrid": "atl. madrid",
        "athletic bilbao": "ath bilbao",
        "borussia monchengladbach": "b. monchengladbach",
        "atletico tucuman": "atl. tucuman",
        # Important mapping for user issue
    }

    def __init__(self, persist_outputs: bool = False):  # Removed unused match_id from __init__
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("Initializing FlashScoreScraper...")
        self.BASE_URL = "https://www.flashscore.com/"

        # ── Hard-guarantee UTC for this Python process (and therefore for
        # the ChromeDriver child process it spawns). ChromeDriver inherits
        # the parent process env, so setting TZ=UTC here ensures Chrome
        # starts in UTC regardless of host OS timezone. This is our first
        # line of defense — CDP `setTimezoneOverride` is the second.
        os.environ["TZ"] = "UTC"
        try:
            time.tzset()  # POSIX only; safe on Linux containers
        except AttributeError:
            pass  # Windows dev — tzset not available

        self.options = Options()
        # Point to Debian's chromium binary (not google-chrome)
        chrome_bin = os.environ.get("CHROME_BIN")
        if chrome_bin:
            self.options.binary_location = chrome_bin
        self.options.add_argument("--headless=new")
        self.options.add_argument('--no-sandbox')
        self.options.add_argument('--disable-dev-shm-usage')
        self.options.add_argument('--disable-gpu')
        self.options.add_argument('--disable-setuid-sandbox')
        self.options.add_argument('--crash-dumps-dir=/tmp/chrome-crashes')
        self.options.add_argument('--remote-debugging-port=0')
        self.options.add_argument('--disable-extensions')
        self.options.add_argument('--disable-background-networking')
        self.options.add_argument("--disable-images")
        self.options.add_argument("--blink-settings=imagesEnabled=false")
        # Pin locale so FlashScore's time format stays deterministic ("18.04.2026 18:45")
        self.options.add_argument("--lang=en-US")
        # Persistence settings
        self.persist_outputs = persist_outputs
        self.output_dir = Path("scraper_outputs") if self.persist_outputs else None
        if self.persist_outputs:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _kill_zombie_chrome():
        """Kill any leftover Chrome/ChromeDriver processes to free memory."""
        try:
            subprocess.run(["pkill", "-f", "chromium"], timeout=5, capture_output=True)
            subprocess.run(["pkill", "-f", "chromedriver"], timeout=5, capture_output=True)
            time.sleep(1)
        except Exception:
            pass

    def _get_driver(self):
        self.logger.debug("Creating new WebDriver instance.")
        # Kill any zombie Chrome processes from previous scrapes
        self._kill_zombie_chrome()
        chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")
        if chromedriver_path:
            service = Service(executable_path=chromedriver_path)
            driver = webdriver.Chrome(service=service, options=self.options)
        else:
            driver = webdriver.Chrome(options=self.options)
        # Force UTC timezone so FlashScore renders all times in UTC,
        # regardless of the server's local timezone. We apply this twice:
        # once here (for early navigations) and once again in
        # `_force_utc_timezone` after each `driver.get(...)` because some
        # CDP overrides don't propagate to already-loaded frames.
        self._force_utc_timezone(driver)
        # FlashScore can also render kickoff in the user's IP-geolocated tz
        # (server-side), independent of Chrome's reported tz. Pin its own
        # preference cookies to UTC so the rendered HH:MM matches what we
        # treat as UTC. Cookies require a prior page load on the same domain.
        self._pin_flashscore_timezone_cookie(driver)
        return driver

    def _pin_flashscore_timezone_cookie(self, driver) -> None:
        """Pin FlashScore's per-user timezone preference to UTC.

        FlashScore decides which timezone to render kickoff times in based
        on a combination of: (a) the JS Date timezone of the page, (b) the
        client IP's geolocation, and (c) a user preference cookie set by
        their settings UI. Chrome's CDP `setTimezoneOverride` only fixes
        (a). Setting the cookie here neutralizes (c) and reduces the
        chance that (b) wins (FlashScore tends to honor an explicit
        preference cookie over geo).

        Cookies require a prior page load on the same eTLD+1, so we
        navigate to the site root once, write the cookies, and let the
        next `driver.get(match_url)` use them.
        """
        try:
            driver.get(self.BASE_URL)
            for name in ("user_tz_offset", "tz_offset", "userTimezoneOffset"):
                try:
                    driver.add_cookie({
                        "name": name,
                        "value": "0",
                        "domain": ".flashscore.com",
                        "path": "/",
                    })
                except Exception:
                    # Cookie API rejects domains for some Selenium builds; retry without
                    try:
                        driver.add_cookie({"name": name, "value": "0", "path": "/"})
                    except Exception:
                        pass
            self.logger.debug("Pinned FlashScore timezone cookies to UTC offset=0.")
        except Exception as e:
            self.logger.warning("Could not pin FlashScore timezone cookies: %s", e)

    def _force_utc_timezone(self, driver) -> None:
        """Apply CDP Emulation.setTimezoneOverride to UTC. Idempotent.

        Call once after driver creation and again after each page load.
        Safe to call repeatedly; CDP treats subsequent calls as updates.
        """
        try:
            driver.execute_cdp_cmd('Emulation.setTimezoneOverride', {'timezoneId': 'UTC'})
        except Exception as e:
            self.logger.warning("Could not set Chrome timezone to UTC: %s", e)

    def _verify_browser_is_utc(self, driver) -> tuple[str, int]:
        """Probe the page for the browser's currently-effective timezone.

        Returns (tz_name, offset_minutes). Logs a WARNING if the browser is
        not running in UTC, so we can alert in production that CDP override
        failed. Offset follows JS convention: ``UTC = local + offset``.
        """
        try:
            tz_name = driver.execute_script(
                "return Intl.DateTimeFormat().resolvedOptions().timeZone;"
            ) or "unknown"
            offset = int(driver.execute_script("return new Date().getTimezoneOffset();"))
        except Exception as e:
            self.logger.warning("Could not probe browser timezone: %s", e)
            return ("unknown", 0)

        if tz_name != "UTC" or offset != 0:
            self.logger.warning(
                "Chrome is NOT running in UTC (tz=%s, offset=%s min). "
                "CDP setTimezoneOverride likely failed silently. "
                "Offset-based conversion will still correct the stored time, "
                "but consider investigating the GCE VM's TZ env var.",
                tz_name, offset,
            )
        else:
            self.logger.debug("Browser timezone verified: UTC (offset=0).")
        return (tz_name, offset)

    def _navigate_to_lineups(self, driver, wait, match_id):
        """Navigate to the lineups tab. Raises on failure."""
        url = f"{self.BASE_URL}match/{match_id}/#/match-summary/match-summary"
        self.logger.info(f"Navigating to: {url}")
        driver.get(url)

        xpaths = [
            "//a[contains(@href, '/lineups/') and contains(@href, 'summary')]",
            "/html/body/div[4]/div[1]/div/div[1]/main/div[5]/div[1]/div[7]/div[1]/div/a[2]/button",
        ]

        for i, xpath in enumerate(xpaths):
            try:
                el = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                time.sleep(0.5)
                try:
                    el.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", el)
                self.logger.info(f"Clicked lineups tab via XPath {i + 1}.")
                break
            except TimeoutException:
                self.logger.warning(f"XPath {i + 1} timed out.")
        else:
            raise RuntimeError("Could not click the Lineups tab with any known XPath.")

        try:
            wait.until(EC.url_contains("/lineups/"))
            self.logger.info(f"Lineups URL confirmed: {driver.current_url}")
        except TimeoutException:

            raise RuntimeError("URL did not update to lineups after clicking tab.")

        time.sleep(5)  # allow dynamic content to render

    def _get_sections_by_title(self, driver, wait):
        """
        Return a dict mapping lowercased section titles → WebElement.
        e.g. {"starting lineups": <el>, "substitutes": <el>}
        """
        try:
            container = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "lf__lineUp")))
            raw_sections = container.find_elements(By.CLASS_NAME, "section")
        except Exception:
            self.logger.warning("'lf__lineUp' not found, falling back to global section search.")
            raw_sections = driver.find_elements(By.CLASS_NAME, "section")

        if not raw_sections:
            raise ValueError("No sections found on the lineups page.")

        sections = {}
        for section in raw_sections:
            try:
                title = section.find_element(
                    By.XPATH, ".//span[@data-testid='wcl-scores-overline-02']"
                ).text.strip().lower()
                sections[title] = section
                self.logger.debug(f"Found section: '{title}'")
            except NoSuchElementException:
                pass

        return sections

    def _extract_text(self, parent, css_selectors):
        """Try each CSS selector in order, return first match's text or None."""
        for selector in css_selectors:
            try:
                return parent.find_element(By.CSS_SELECTOR, selector).text.strip()
            except NoSuchElementException:
                continue
        return None

    def _save_debug_screenshot(self, driver, filename):
        """Save a screenshot only if persist_outputs is enabled."""
        if self.persist_outputs and self.output_dir:
            try:
                driver.save_screenshot(self.output_dir / filename)
            except Exception:
                pass

    def _parse_sides(self, section, side_keys=("home_team", "away_team")):
        """
        Given a section WebElement with lf__sidesBox > lf__side children,
        return a dict: {side_key: [{"player_name": ..., "jersey_number": ...}, ...]}
        """
        try:
            sides_box = section.find_element(By.CLASS_NAME, "lf__sidesBox")
        except NoSuchElementException:
            sides_box = section  # fallback: sides directly inside section

        sides = sides_box.find_elements(By.CLASS_NAME, "lf__side")
        result = {}

        for idx, side_el in enumerate(sides):
            key = side_keys[idx] if idx < len(side_keys) else f"team_{idx}"
            players = []

            for participant in side_el.find_elements(By.CSS_SELECTOR, ".lf__participantNew"):
                name = self._extract_text(participant, [
                    ".wcl-simpleText_2t3pL.wcl-scores-simple-text-01_ntYoG.wcl-bold_MMDhq.wcl-name_ZggyJ",
                    "strong[data-testid='wcl-scores-simple-text-01']",
                ])
                jersey = self._extract_text(participant, [
                    ".wcl-simpleText_2t3pL.wcl-scores-simple-text-01_ntYoG.wcl-number_lTBFk",
                    ".wcl-number_lTBFk",
                ])
                players.append({"player_name": name or "N/A", "jersey_number": jersey or "N/A"})

            result[key] = players
            self.logger.info(f"Parsed {len(players)} players for {key}.")

        return result

    def _accept_privacy_or_cookies(self, driver):
        """Attempt to accept privacy/cookie dialogs that block interactions."""
        try:
            wait = WebDriverWait(driver, 8)
            candidates = [
                (By.ID, "onetrust-accept-btn-handler"),
                (By.CSS_SELECTOR, "#onetrust-accept-btn-handler"),
                (By.XPATH, "//button[contains(., 'Accept All')]"),
                (By.XPATH,
                 "//button[contains(., 'I Accept') or contains(., 'I agree') or contains(., 'Allow all') or contains(., 'Accept all')]")
            ]
            for by, sel in candidates:
                try:
                    btn = wait.until(EC.element_to_be_clickable((by, sel)))
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", btn)
                    time.sleep(0.2)
                    try:
                        btn.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", btn)
                    self.logger.info("Accepted cookie/privacy dialog.")
                    time.sleep(0.3)
                    return
                except TimeoutException:
                    continue
                except Exception:
                    continue
        except Exception as e:
            self.logger.debug(f"No cookie/privacy dialog handled: {e}")

    def normalize_team_name(self, team_name: str):
        self.logger.debug(f"Normalizing team name: {team_name}")
        team_name_lower = team_name.lower()
        if not self.TEAM_NAME_ABBREVIATIONS:  # Handle empty dict
            self.logger.info(f"TEAM_NAME_ABBREVIATIONS is empty. Using '{team_name_lower}' as is.")
            return team_name_lower
        best_match = process.extractOne(team_name_lower, self.TEAM_NAME_ABBREVIATIONS.keys(), scorer=fuzz.partial_ratio)
        if best_match and best_match[1] > 80:
            normalized = self.TEAM_NAME_ABBREVIATIONS[best_match[0]]
            self.logger.info(f"Normalized '{team_name}' to '{normalized}' using abbreviations.")
            return normalized
        self.logger.info(f"No strong abbreviation match for '{team_name}', using it as is (lowercased).")
        return team_name_lower

    def scrape_lineups_and_substitutions(self, match_id):
        """
        Single-session scrape of both starting lineups and substitutes.

        Returns:
            dict with keys:
              "lineups"       → {home_team: {jersey: name}, away_team: {jersey: name}}
              "substitutes"   → {home_team: [players], away_team: [players]}
        """
        self.logger.info(f"Scraping lineups + substitutions for match: {match_id}")
        driver = self._get_driver()

        try:
            wait = WebDriverWait(driver, 60)
            self._navigate_to_lineups(driver, wait, match_id)

            sections = self._get_sections_by_title(driver, wait)

            # --- Starting Lineups ---
            lineup_section = next(
                (s for title, s in sections.items() if "starting" in title or "lineup" in title),
                None
            )
            self.logger.info(f"Looking for starting lineups section among {len(sections)} sections.")
            if lineup_section is None:
                raise ValueError(f"No starting lineups section found. Sections found: {list(sections.keys())}")

            raw_lineups = self._parse_sides(lineup_section)
            self.logger.info(f"Raw lineups parsed: { {team: len(players) for team, players in raw_lineups.items()} }")
            # Reshape to {jersey: name} dict per team (original contract)
            lineups = {
                team: {p["jersey_number"]: p["player_name"] for p in players}
                for team, players in raw_lineups.items()
            }

            # --- Substitutes ---
            self.logger.info("Looking for substitutes section.")
            sub_section = next(
                (s for title, s in sections.items() if "substitutes" in title),
                None
            )
            self.logger.info(f"Substitutes section found: {'Yes' if sub_section else 'No'}")
            if sub_section is None:
                self.logger.warning("No substitutes section found.")
                substitutes = {"home_team": [], "away_team": []}
            else:
                raw_subs = self._parse_sides(sub_section)
                substitutes = {
                    team: [p["player_name"] for p in players]
                    for team, players in raw_subs.items()
                }

            result = {"lineups": lineups, "substitutes": substitutes}

            if self.persist_outputs and self.output_dir:
                out_path = self.output_dir / f"match_{match_id}_lineups_and_subs.json"
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=4)
                self.logger.info(f"Saved combined output to {out_path}")
            self.logger.info(f"Successfully scraped match {match_id}")
            return result

        except Exception as e:
            self.logger.error(f"Failed scraping match {match_id}: {e}", exc_info=True)
            self._save_debug_screenshot(driver, f"error_{match_id}.png")
            raise
        finally:
            driver.quit()

    def get_team_id_by_name(self, home_team: str):
        self.logger.info(f"Attempting to get match ID for team: {home_team}")
        driver = self._get_driver()
        try:
            normalized_team_name = self.normalize_team_name(home_team)
            team_lower = normalized_team_name.lower()
            # Target the home participant name cell and match text case-insensitively
            team_element_xpath = (
                f"//div[contains(@class, 'wcl-participants')]"
                f"//span[contains(@data-testid, 'wcl-scores-simple-text-01') and contains(translate(normalize-space(.), "
                f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{team_lower}')]"
            )

            self.logger.info(f"Navigating to base URL: {self.BASE_URL}")
            driver.get(self.BASE_URL)
            # Try to accept cookie/privacy prompts if present
            try:
                self._accept_privacy_or_cookies(driver)
            except Exception:
                pass
            wait = WebDriverWait(driver, 15)  # Increased wait time

            self.logger.info(f"Searching for home team element with XPath: {team_element_xpath}")
            team_name_elements = []
            try:
                team_name_elements = wait.until(EC.presence_of_all_elements_located((By.XPATH, team_element_xpath)))
            except TimeoutException:
                self.logger.warning("Initial homepage scan timed out. Will try fallback search flow.")

            if not team_name_elements:
                self.logger.info(
                    f"No team elements found for '{normalized_team_name}' on homepage. Trying search page flow.")
            else:
                self.logger.info(
                    f"Found {len(team_name_elements)} potential matches for team name. Checking first one for a valid match structure.")

            match_id = None
            for team_element in team_name_elements:  # Iterate through found elements to find a valid one
                try:
                    # Try to find the ancestor div that contains the match ID (e.g., id="g_1_8CroQLLc")
                    ancestor_div = team_element.find_element(By.XPATH, ".//ancestor::div[starts-with(@id, 'g_')]")
                    match_id_attr = ancestor_div.get_attribute("id")
                    self.logger.info(f"Found potential ancestor div with ID: {match_id_attr}")

                    # Extract match ID: g_1_xxxxxxx -> xxxxxxx or g_4_xxxxxxx -> xxxxxxx
                    parsed_id = re.sub(r'^g_\d+_', '', match_id_attr)
                    if parsed_id and parsed_id != match_id_attr:  # Check if substitution happened
                        match_id = parsed_id
                        self.logger.info(
                            f"Successfully extracted match ID: {match_id} for team {home_team} from element.")
                        return match_id
                    else:
                        self.logger.debug(
                            f"Could not parse a clean match_id from attribute '{match_id_attr}' for one of the elements.")
                except NoSuchElementException:
                    # Fallback: The row often has an <a class='eventRowLink' aria-describedby='g_1_XXXXX'>
                    try:
                        row_anchor = team_element.find_element(By.XPATH,
                                                               ".//ancestor::div[contains(@class,'event__match') or contains(@class,'eventRow')]//a[contains(@class,'eventRowLink') and @aria-describedby]")
                        described_by = row_anchor.get_attribute('aria-describedby')
                        if described_by and described_by.startswith('g_'):
                            parsed_id = re.sub(r'^g_\d+_', '', described_by)
                            if parsed_id and parsed_id != described_by:
                                self.logger.info(f"Extracted match ID from aria-describedby: {parsed_id}")
                                return parsed_id
                    except Exception:
                        self.logger.debug(
                            "One of the matched team name elements did not have the expected ancestor or row anchor for ID.")
                continue  # Try next element

            # Fallback: Use the search page to locate the team, then pick a match ID from the team page
            try:
                search_url = f"{self.BASE_URL}search/?q={quote(normalized_team_name)}"
                self.logger.info(f"Navigating to search URL: {search_url}")
                driver.get(search_url)
                try:
                    self._accept_privacy_or_cookies(driver)
                except Exception:
                    pass
                # Results may take a bit; increase wait slightly
                wait = WebDriverWait(driver, 20)

                # Find potential team links
                self.logger.info("Looking for team links in search results...")
                team_links = wait.until(EC.presence_of_all_elements_located((
                    By.XPATH,
                    "//a[contains(@href, '/team/')][normalize-space(string())!='']"
                )))

                # Choose the best match by fuzzy string similarity on visible text
                best_link = None
                best_score = -1
                for link in team_links:
                    try:
                        text = (link.text or "").strip().lower()
                        if not text:
                            continue
                        score = fuzz.token_set_ratio(text, normalized_team_name.lower())
                        if score > best_score:
                            best_score = score
                            best_link = link
                    except Exception:
                        continue

                if not best_link:
                    self.logger.error("No team links found on search results page.")
                    if self.persist_outputs and self.output_dir is not None:
                        try:
                            driver.save_screenshot(
                                self.output_dir / f"error_search_no_team_{home_team.replace(' ', '_')}.png")
                        except Exception:
                            pass
                    raise Exception("Team not found via search page.")

                self.logger.info(f"Clicking best team link (score {best_score}).")
                try:
                    best_link.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", best_link)

                # Wait for navigation to team page
                wait.until(EC.url_contains("/team/"))
                time.sleep(1.5)

                # On the team page, look for any match containers with ids like g_1_XXXX or g_4_XXXX
                self.logger.info("Searching for match containers with id starting 'g_'.")
                match_divs = wait.until(
                    EC.presence_of_all_elements_located((By.XPATH, "//div[starts-with(@id, 'g_')]")))
                if not match_divs:
                    self.logger.error("No match containers found on team page.")
                    if self.persist_outputs and self.output_dir is not None:
                        try:
                            driver.save_screenshot(
                                self.output_dir / f"error_team_page_no_matches_{home_team.replace(' ', '_')}.png")
                        except Exception:
                            pass
                    raise Exception("No matches listed on team page.")

                # Prefer live or upcoming by rough heuristic: the first element usually is closest/upcoming
                match_id_attr = match_divs[0].get_attribute("id")
                parsed_id = re.sub(r'^g_\d+_', '', match_id_attr)
                if parsed_id and parsed_id != match_id_attr:
                    self.logger.info(f"Extracted match ID from team page: {parsed_id}")
                    return parsed_id

                # If parsing failed, iterate to find a parsable id
                for div in match_divs[1:]:
                    mid_attr = div.get_attribute("id")
                    parsed = re.sub(r'^g_\d+_', '', mid_attr)
                    if parsed and parsed != mid_attr:
                        self.logger.info(f"Extracted match ID from team page (later element): {parsed}")
                        return parsed

                self.logger.error("Could not parse any match IDs from team page containers.")
                if self.persist_outputs and self.output_dir is not None:
                    try:
                        driver.save_screenshot(
                            self.output_dir / f"error_team_page_cannot_parse_{home_team.replace(' ', '_')}.png")
                    except Exception:
                        pass
                raise Exception("Could not parse match ID from team page.")
            except Exception as fallback_error:
                self.logger.error(f"Fallback search flow failed: {fallback_error}")
                # Fallback 2: Use header search UI to trigger results, then select a team
                try:
                    self.logger.info("Attempting header search UI flow.")
                    driver.get(self.BASE_URL)
                    try:
                        self._accept_privacy_or_cookies(driver)
                    except Exception:
                        pass
                    wait = WebDriverWait(driver, 20)
                    # Try opening the search input
                    # 1) Focus any input with placeholder containing 'Search'
                    input_field = None
                    try:
                        input_field = wait.until(EC.presence_of_element_located((
                            By.XPATH,
                            "//input[@type='text' and contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'search')]"
                        )))
                    except Exception:
                        # 2) If not present, click a generic search button to reveal it
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
                    input_field.send_keys(normalized_team_name)
                    time.sleep(0.5)

                    team_links = wait.until(EC.presence_of_all_elements_located((
                        By.XPATH,
                        "(//a[contains(@href, '/team/')])[position()<=10]"
                    )))

                    best_link = None
                    best_score = -1
                    for link in team_links:
                        try:
                            text = (link.text or "").strip().lower()
                            if not text:
                                continue
                            score = fuzz.token_set_ratio(text, normalized_team_name.lower())
                            if score > best_score:
                                best_score = score
                                best_link = link
                        except Exception:
                            continue

                    if not best_link:
                        if self.persist_outputs and self.output_dir is not None:
                            try:
                                driver.save_screenshot(
                                    self.output_dir / f"error_header_search_no_team_{home_team.replace(' ', '_')}.png")
                            except Exception:
                                pass
                        raise Exception("Team not found via header search UI")

                    try:
                        best_link.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", best_link)

                    wait.until(EC.url_contains("/team/"))
                    time.sleep(1.0)

                    match_divs = wait.until(
                        EC.presence_of_all_elements_located((By.XPATH, "//div[starts-with(@id, 'g_')]")))
                    for div in match_divs:
                        mid_attr = div.get_attribute("id")
                        parsed = re.sub(r'^g_\d+_', '', mid_attr)
                        if parsed and parsed != mid_attr:
                            self.logger.info(f"Extracted match ID from team page (header search): {parsed}")
                            return parsed

                    if self.persist_outputs and self.output_dir is not None:
                        try:
                            driver.save_screenshot(
                                self.output_dir / f"error_header_search_no_matches_{home_team.replace(' ', '_')}.png")
                        except Exception:
                            pass
                    raise Exception("Could not parse match ID after header search UI flow")

                except Exception as header_fallback_error:
                    self.logger.error(f"Header search UI flow failed: {header_fallback_error}")
                    raise

        except Exception as e:
            self.logger.error(f"An error occurred while searching for team '{home_team}': {str(e)}", exc_info=True)
            if self.persist_outputs and self.output_dir is not None:
                try:
                    driver.save_screenshot(self.output_dir / f"error_get_team_id_{home_team.replace(' ', '_')}.png")
                except Exception:
                    pass
            raise Exception(f"Failed to get match ID for team {home_team}: {str(e)}")
        finally:
            self.logger.debug("Quitting WebDriver for get_team_id_by_name.")
            if driver:
                driver.quit()

    def get_odds_by_match_name(self, match_name: str):
        self.logger.info("Scraping odds for match: %s", match_name)
        match_id = self.get_team_id_by_name(match_name)
        if not match_id:
            self.logger.error("Could not find match ID for match name: %s", match_name)
            raise ValueError(f"Match ID not found for {match_name}")

        self.logger.info("Found match ID: %s", match_id)
        driver = self._get_driver()

        try:
            # Step 1: Land on match summary first — let the SPA fully initialise
            summary_url = f"{self.BASE_URL}match/{match_id}/#/match-summary/match-summary"
            self.logger.info("Navigating to match summary: %s", summary_url)
            driver.get(summary_url)

            wait = WebDriverWait(driver, 20)
            self._accept_privacy_or_cookies(driver)

            # Step 2: Click the Odds tab — same pattern as lineups scraper
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
                self.logger.error("Could not click odds tab — logging available tabs for diagnosis.")
                # Log all nav links so we can see what tabs actually exist
                nav_links = driver.find_elements(By.XPATH, "//a[contains(@href, '/match/')]")
                for link in nav_links:
                    self.logger.debug("Nav link: text='%s' href='%s'",
                                      link.text.strip(), link.get_attribute("href"))
                if self.persist_outputs and self.output_dir:
                    driver.save_screenshot(self.output_dir / f"debug_no_odds_tab_{match_id}.png")
                raise RuntimeError(f"Could not find or click the Odds tab for match {match_id}")

            # Step 3: Confirm URL updated to odds comparison
            try:
                wait.until(EC.url_contains("odds-comparison"))
                self.logger.info("Odds URL confirmed: %s", driver.current_url)
            except TimeoutException:
                self.logger.warning(
                    "URL did not update to odds-comparison. Current URL: %s", driver.current_url
                )
                # Don't raise — some matches load odds without URL update; try scraping anyway

            # Step 4: Wait for the odds table rows
            time.sleep(2)

            ROW_XPATH = "//div[contains(@class,'ui-table__row')]"
            HOME_ODD_XPATH = ".//a[contains(@data-analytics-element,'ODD_CELL_1')]//span"
            DRAW_ODD_XPATH = ".//a[contains(@data-analytics-element,'ODD_CELL_2')]//span"
            AWAY_ODD_XPATH = ".//a[contains(@data-analytics-element,'ODD_CELL_3')]//span"
            BOOKMAKER_XPATH = ".//img[contains(@class,'wcl-logoImage')]"

            try:
                wait.until(EC.presence_of_element_located((By.XPATH, ROW_XPATH)))
            except TimeoutException:
                # Odds may be unavailable for this match (finished/future/region-blocked)
                try:
                    body_snippet = driver.find_element(By.TAG_NAME, "body").text[:500]
                    self.logger.warning("Odds table not found. Page text snippet:\n%s", body_snippet)
                except Exception:
                    pass
                if self.persist_outputs and self.output_dir:
                    driver.save_screenshot(self.output_dir / f"debug_no_odds_table_{match_id}.png")
                return {"home": None, "draw": None, "away": None,
                        "bookmaker": None, "source_url": driver.current_url}

            rows = driver.find_elements(By.XPATH, ROW_XPATH)
            self.logger.info("Found %d odds rows.", len(rows))

            for row_idx, row in enumerate(rows):
                try:
                    home_odd = row.find_element(By.XPATH, HOME_ODD_XPATH).text.strip()
                    draw_odd = row.find_element(By.XPATH, DRAW_ODD_XPATH).text.strip()
                    away_odd = row.find_element(By.XPATH, AWAY_ODD_XPATH).text.strip()

                    self.logger.debug(
                        "Row %d — home: '%s' | draw: '%s' | away: '%s'",
                        row_idx, home_odd, draw_odd, away_odd
                    )

                    if not all(self._is_valid_odd(o) for o in (home_odd, draw_odd, away_odd)):
                        self.logger.debug("Row %d skipped — non-numeric or invalid odds.", row_idx)
                        continue

                    try:
                        bookmaker = row.find_element(By.XPATH, BOOKMAKER_XPATH).get_attribute("alt")
                    except NoSuchElementException:
                        bookmaker = "Unknown"

                    result = {
                        "home": float(home_odd),
                        "draw": float(draw_odd),
                        "away": float(away_odd),
                        "bookmaker": bookmaker,
                        "source_url": driver.current_url,
                    }
                    self.logger.info(
                        "Odds from '%s' — home: %s | draw: %s | away: %s",
                        bookmaker, home_odd, draw_odd, away_odd
                    )
                    return result

                except NoSuchElementException:
                    self.logger.debug("Row %d has no ODD_CELL anchors, skipping.", row_idx)
                    continue

            self.logger.warning("No valid odds row found for match: %s", match_name)
            return {"home": None, "draw": None, "away": None,
                    "bookmaker": None, "source_url": driver.current_url}

        except Exception as e:
            self.logger.error("Error scraping odds for '%s': %s", match_name, e, exc_info=True)
            if self.persist_outputs and self.output_dir:
                try:
                    driver.save_screenshot(self.output_dir / f"error_odds_{match_id}.png")
                except Exception:
                    pass
            raise

        finally:
            driver.quit()

    def get_odds_by_match_id(self, match_id: str) -> dict:
        """
        Scrape odds directly using a known FlashScore match ID.
        Skips the team name → match ID resolution step entirely.
        """
        self.logger.info("Scraping odds directly for match_id: %s", match_id)
        driver = self._get_driver()

        try:
            # Go straight to match summary to initialise the SPA
            summary_url = f"{self.BASE_URL}match/{match_id}/#/match-summary/match-summary"
            self.logger.info("Navigating to match summary: %s", summary_url)
            driver.get(summary_url)

            wait = WebDriverWait(driver, 20)
            self._accept_privacy_or_cookies(driver)

            # Click the Odds tab
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
                raise RuntimeError(f"Could not find or click the Odds tab for match {match_id}")

            # Wait for odds table
            time.sleep(2)
            ROW_XPATH = "//div[contains(@class,'ui-table__row')]"
            HOME_ODD_XPATH = ".//a[contains(@data-analytics-element,'ODD_CELL_1')]//span"
            DRAW_ODD_XPATH = ".//a[contains(@data-analytics-element,'ODD_CELL_2')]//span"
            AWAY_ODD_XPATH = ".//a[contains(@data-analytics-element,'ODD_CELL_3')]//span"
            BOOKMAKER_XPATH = ".//img[contains(@class,'wcl-logoImage')]"

            try:
                wait.until(EC.presence_of_element_located((By.XPATH, ROW_XPATH)))
            except TimeoutException:
                self.logger.warning("Odds table not found for match %s", match_id)
                return {"home": None, "draw": None, "away": None,
                        "bookmaker": None, "source_url": driver.current_url}

            rows = driver.find_elements(By.XPATH, ROW_XPATH)
            self.logger.info("Found %d odds rows.", len(rows))

            for row_idx, row in enumerate(rows):
                try:
                    home_odd = row.find_element(By.XPATH, HOME_ODD_XPATH).text.strip()
                    draw_odd = row.find_element(By.XPATH, DRAW_ODD_XPATH).text.strip()
                    away_odd = row.find_element(By.XPATH, AWAY_ODD_XPATH).text.strip()

                    if not all(self._is_valid_odd(o) for o in (home_odd, draw_odd, away_odd)):
                        continue

                    try:
                        bookmaker = row.find_element(By.XPATH, BOOKMAKER_XPATH).get_attribute("alt")
                    except NoSuchElementException:
                        bookmaker = "Unknown"

                    result = {
                        "home": float(home_odd),
                        "draw": float(draw_odd),
                        "away": float(away_odd),
                        "bookmaker": bookmaker,
                        "source_url": driver.current_url,
                    }
                    self.logger.info(
                        "Odds — home: %s | draw: %s | away: %s | bookmaker: %s",
                        home_odd, draw_odd, away_odd, bookmaker
                    )
                    return result

                except NoSuchElementException:
                    continue

            self.logger.warning("No valid odds row found for match %s", match_id)
            return {"home": None, "draw": None, "away": None,
                    "bookmaker": None, "source_url": driver.current_url}

        except Exception as e:
            self.logger.error("Error scraping odds for match_id '%s': %s", match_id, e, exc_info=True)
            raise

        finally:
            driver.quit()

    @staticmethod
    def _is_valid_odd(value: str) -> bool:
        """Return True if the string is a positive float (e.g. '2.75')."""
        try:
            return float(value) > 1.0
        except (ValueError, TypeError):
            return False

    def get_match_info(self, match_id: str) -> dict:
        """
        Scrape match metadata: home team, away team, and start time.
        Called ONCE when a match is first registered for tracking.
        Returns a dict with keys: home_team, away_team, start_time (UTC ISO string)
        """
        driver = self._get_driver()

        try:
            url = f"{self.BASE_URL}match/{match_id}/#/match-summary/match-summary"
            self.logger.info("Fetching match info from: %s", url)
            driver.get(url)

            wait = WebDriverWait(driver, 20)
            self._accept_privacy_or_cookies(driver)

            # --- Team names ---
            # These are stable across FlashScore matches
            home_team = self._safe_text(driver, [
                "//div[contains(@class,'duelParticipant__home')]//a[contains(@class,'participant__participantName')]",
                "//div[contains(@class,'duelParticipant__home')]//div[contains(@class,'participant__participantName')]",
            ])

            away_team = self._safe_text(driver, [
                "//div[contains(@class,'duelParticipant__away')]//a[contains(@class,'participant__participantName')]",
                "//div[contains(@class,'duelParticipant__away')]//div[contains(@class,'participant__participantName')]",
            ])

            # --- Start time ---
            # FlashScore renders the time as a single string like "26.02.2026 21:00"
            # in an element with class startTime or duelParticipant__startTime
            raw_start_time = self._safe_text(driver, [
                "//div[contains(@class,'duelParticipant__startTime')]//div",
                "//div[contains(@class,'startTime')]",
                "//span[contains(@class,'startTime')]",
            ])

            # Detect Chrome's actual timezone offset (in minutes) at this page.
            # JS getTimezoneOffset() returns (UTC - local) in minutes, e.g.
            # UTC → 0, CET → -60, Morocco GMT+1 → -60, PST → 480.
            # We pass it to the parser so that even if setTimezoneOverride
            # silently failed we still convert FlashScore's rendered time
            # to UTC correctly.
            tz_offset_minutes = self._detect_browser_tz_offset(driver)

            self.logger.info(
                "Raw match info — home: '%s' | away: '%s' | start_time: '%s' | browser_tz_offset=%s min",
                home_team, away_team, raw_start_time, tz_offset_minutes,
            )

            start_time_utc = self._parse_flashscore_datetime(
                raw_start_time, match_id, tz_offset_minutes=tz_offset_minutes,
            )

            return {
                "home_team": home_team or "unknown",
                "away_team": away_team or "unknown",
                "start_time": start_time_utc,  # UTC ISO 8601 string or None
                "start_time_raw": raw_start_time,  # keep raw for debugging
            }

        except Exception as e:
            self.logger.error("Failed to get match info for %s: %s", match_id, e, exc_info=True)
            raise

        finally:
            driver.quit()

    def _safe_text(self, driver, xpaths: list[str]) -> str | None:
        """Try each XPath in order, return first non-empty text found."""
        for xpath in xpaths:
            try:
                el = driver.find_element(By.XPATH, xpath)
                text = el.text.strip()
                if text:
                    return text
            except NoSuchElementException:
                continue
        return None

    def _detect_browser_tz_offset(self, driver) -> int:
        """
        Ask the currently-loaded page what timezone Chrome is actually
        using. This is our last-line-of-defense for time correctness:
        even if CDP `setTimezoneOverride` silently fails and TZ=UTC env
        is missing, FlashScore's rendered time + this offset = correct UTC.

        Also re-applies the UTC CDP override — some Chrome builds require
        a second apply after the page's Document is loaded.

        Returns the offset in minutes such that ``UTC = local + offset``
        (JS convention — positive = west of UTC). Returns 0 on failure
        (equivalent to assuming the raw time is already UTC).
        """
        # Belt-and-suspenders: re-apply the override now that a real page
        # is loaded, then probe to see whether it actually took effect.
        self._force_utc_timezone(driver)
        tz_name, offset = self._verify_browser_is_utc(driver)
        self.logger.info("Browser timezone at scrape: tz=%s, offset=%s min", tz_name, offset)
        return offset

    def _parse_flashscore_datetime(
        self,
        raw: str | None,
        match_id: str,
        tz_offset_minutes: int = 0,
    ) -> str | None:
        """
        Parse FlashScore date strings into UTC ISO 8601.

        FlashScore formats encountered:
          "26.02.2026 21:00"   — date + time
          "26.02. 21:00"       — day/month only (current year implied)
          "21:00"              — time only (today implied, rare)

        We try to force Chrome to UTC via CDP (Emulation.setTimezoneOverride),
        but that can fail silently. The caller should therefore detect the
        actual browser timezone with ``_detect_browser_tz_offset`` and pass
        it here as ``tz_offset_minutes`` (JS convention: ``UTC = local + offset``).
        Defaults to 0 for back-compat — equivalent to assuming the raw
        string is already in UTC.
        """
        import re
        from datetime import datetime, timezone, timedelta

        if not raw:
            self.logger.warning("No start time text found for match %s", match_id)
            return None

        now = datetime.now(timezone.utc)

        def _to_utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
            """Convert a naive local datetime (in the browser's tz) to UTC."""
            local_dt = datetime(year, month, day, hour, minute)
            return (local_dt + timedelta(minutes=tz_offset_minutes)).replace(tzinfo=timezone.utc)

        def _sanity_check(utc_dt: datetime, label: str) -> None:
            """Warn if the parsed UTC time is absurdly far from now.

            Classic tz-drift symptom: a future match parsed as already
            completed (many hours in the past) or scheduled days in the
            future. Not a hard error — just a loud signal in logs.
            """
            delta = utc_dt - now
            hours = delta.total_seconds() / 3600.0
            if hours < -12:
                self.logger.warning(
                    "Parsed start time %s is %.1fh in the past for match %s (raw=%r, tz_offset=%s). "
                    "This likely means Chrome's timezone drifted and the offset correction is wrong.",
                    utc_dt.isoformat(), hours, match_id, raw, tz_offset_minutes,
                )
            elif hours > 24 * 14:
                self.logger.warning(
                    "Parsed start time %s is %.1f days in the future for match %s (raw=%r). Suspicious.",
                    utc_dt.isoformat(), hours / 24, match_id, raw,
                )

        # Pattern 1: "26.02.2026 21:00" — full date with year
        match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})", raw)
        if match:
            day, month, year, hour, minute = map(int, match.groups())
            utc_dt = _to_utc(year, month, day, hour, minute)
            utc_iso = utc_dt.isoformat()
            self.logger.info("Parsed start time (full): %s → %s (tz_offset=%s)", raw, utc_iso, tz_offset_minutes)
            _sanity_check(utc_dt, "full")
            return utc_iso

        # Pattern 2: "26.02. 21:00" — no year, assume current year
        match = re.search(r"(\d{2})\.(\d{2})\.\s+(\d{2}):(\d{2})", raw)
        if match:
            day, month, hour, minute = map(int, match.groups())
            year = now.year
            utc_dt = _to_utc(year, month, day, hour, minute)
            # Roll over to next year if date already passed
            if utc_dt < now:
                utc_dt = _to_utc(year + 1, month, day, hour, minute)
            utc_iso = utc_dt.isoformat()
            self.logger.info("Parsed start time (no year): %s → %s (tz_offset=%s)", raw, utc_iso, tz_offset_minutes)
            _sanity_check(utc_dt, "no-year")
            return utc_iso

        # Pattern 3: "21:00" — time only, assume today
        match = re.search(r"(\d{2}):(\d{2})", raw)
        if match:
            hour, minute = map(int, match.groups())
            utc_dt = _to_utc(now.year, now.month, now.day, hour, minute)
            utc_iso = utc_dt.isoformat()
            self.logger.info("Parsed start time (time only): %s → %s (tz_offset=%s)", raw, utc_iso, tz_offset_minutes)
            _sanity_check(utc_dt, "time-only")
            return utc_iso

        self.logger.warning("Could not parse start time '%s' for match %s", raw, match_id)
        return None
