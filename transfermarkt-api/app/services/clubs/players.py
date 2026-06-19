from dataclasses import dataclass
from datetime import datetime

from app.services.base import TransfermarktBase
from app.utils.regex import REGEX_DOB
from app.utils.utils import clean_response, extract_from_url, safe_regex
from app.utils.xpath import Clubs


@dataclass
class TransfermarktClubPlayers(TransfermarktBase):
    """
    A class for retrieving and parsing the players of a football club from Transfermarkt.

    Args:
        club_id (str): The unique identifier of the football club.
        season_id (str): The unique identifier of the season.
        URL (str): The URL template for the club's players page on Transfermarkt.
    """

    club_id: str = None
    season_id: str = None
    URL: str = "https://www.transfermarkt.com/-/kader/verein/{club_id}/saison_id/{season_id}/plus/1"

    def __post_init__(self) -> None:
        """Initialize the TransfermarktClubPlayers class."""
        self.URL = self.URL.format(club_id=self.club_id, season_id=self.season_id)
        self.page = self.request_url_page()
        self.raise_exception_if_not_found(xpath=Clubs.Players.CLUB_NAME)
        self.__update_season_id()
        self.__update_past_flag()

    def __update_season_id(self):
        """Update the season ID if it's not provided by extracting it from the website."""
        if self.season_id is None:
            self.season_id = extract_from_url(self.get_text_by_xpath(Clubs.Players.CLUB_URL), "season_id")

    def __update_past_flag(self) -> None:
        """Check if the season is the current or if it's a past one and update the flag accordingly."""
        self.past = "Current club" in self.get_list_by_xpath(Clubs.Players.PAST_FLAG)

    def __parse_club_players(self) -> list[dict]:
        """
        Parse player information from the webpage and return a list of dictionaries, each representing a player.

        Returns:
            list[dict]: A list of player information dictionaries.
        """
        page_nationalities = self.page.xpath(Clubs.Players.PAGE_NATIONALITIES)
        page_players_infos = self.page.xpath(Clubs.Players.PAGE_INFOS)
        page_players_signed_from = self.page.xpath(
            Clubs.Players.Past.PAGE_SIGNED_FROM if self.past else Clubs.Players.Present.PAGE_SIGNED_FROM,
        )
        page_players_joined_on = self.page.xpath(
            Clubs.Players.Past.PAGE_JOINED_ON if self.past else Clubs.Players.Present.PAGE_JOINED_ON,
        )
        players_ids = [extract_from_url(url) for url in self.get_list_by_xpath(Clubs.Players.URLS)]
        players_names = self.get_list_by_xpath(Clubs.Players.NAMES)
        players_positions = self.get_list_by_xpath(Clubs.Players.POSITIONS)
        players_dobs = [
            safe_regex(dob_age, REGEX_DOB, "dob") for dob_age in self.get_list_by_xpath(Clubs.Players.DOB_AGE)
        ]
        players_ages = [
            safe_regex(dob_age, REGEX_DOB, "age") for dob_age in self.get_list_by_xpath(Clubs.Players.DOB_AGE)
        ]
        players_nationalities = [nationality.xpath(Clubs.Players.NATIONALITIES) for nationality in page_nationalities]
        players_current_club = (
            self.get_list_by_xpath(Clubs.Players.Past.CURRENT_CLUB) if self.past else [None] * len(players_ids)
        )
        players_heights = self.get_list_by_xpath(
            Clubs.Players.Past.HEIGHTS if self.past else Clubs.Players.Present.HEIGHTS,
        )
        players_jerseys = self.get_list_by_xpath(
            Clubs.Players.JERSES
        )
        players_foots = self.get_list_by_xpath(
            Clubs.Players.Past.FOOTS if self.past else Clubs.Players.Present.FOOTS,
            remove_empty=False,
        )
        players_joined_on = ["; ".join(e.xpath(Clubs.Players.JOINED_ON)) for e in page_players_joined_on]
        players_joined = ["; ".join(e.xpath(Clubs.Players.JOINED)) for e in page_players_infos]
        players_signed_from = ["; ".join(e.xpath(Clubs.Players.SIGNED_FROM)) for e in page_players_signed_from]
        players_contracts = (
            [None] * len(players_ids) if self.past else self.get_list_by_xpath(Clubs.Players.Present.CONTRACTS)
        )
        players_marketvalues = self.get_list_by_xpath(Clubs.Players.MARKET_VALUES)
        players_statuses = ["; ".join(e.xpath(Clubs.Players.STATUSES)) for e in page_players_infos]

        # National-team squad pages (and the occasional club row) don't render
        # a shirt number, so JERSES — and, less often, other optional columns —
        # come back SHORTER than the per-player columns. The previous zip()
        # truncated the whole roster to the shortest list, which for national
        # teams (no shirt numbers at all → empty jersey list) yielded ZERO
        # players and an empty comparison. We anchor on the player rows
        # (ids/names, one per squad row) and pad the rest, so a missing jersey
        # just blanks out instead of dropping the player. Downstream lineup
        # matching already falls back to name when the jersey is absent.
        num_players = max(len(players_ids), len(players_names))

        def _col(values: list, i: int):
            return values[i] if i < len(values) else None

        return [
            {
                "id": _col(players_ids, i),
                "name": _col(players_names, i),
                "position": _col(players_positions, i),
                "dateOfBirth": _col(players_dobs, i),
                "age": _col(players_ages, i),
                "nationality": _col(players_nationalities, i),
                "currentClub": _col(players_current_club, i),
                "height": _col(players_heights, i),
                "foot": _col(players_foots, i),
                "joinedOn": _col(players_joined_on, i),
                "joined": _col(players_joined, i),
                "signedFrom": _col(players_signed_from, i),
                "contract": _col(players_contracts, i),
                "marketValue": _col(players_marketvalues, i),
                "status": _col(players_statuses, i),
                # Blank (not None) when absent so downstream str() handling and
                # jersey→name fallback behave predictably.
                "jersey_number": _col(players_jerseys, i) or "",
            }
            # Skip padded rows that have no name — those are an artefact of a
            # column being longer than the id/name columns, not real players.
            for i in range(num_players)
            if _col(players_names, i)
        ]

    def get_club_players(self) -> dict:
        """
        Retrieve and parse player information for the specified football club.

        Returns:
            dict: A dictionary containing the club's unique identifier, player information, and the timestamp of when
                  the data was last updated.
        """
        self.response["id"] = self.club_id
        self.response["players"] = self.__parse_club_players()
        self.response["updatedAt"] = datetime.now()
        return clean_response(self.response)
