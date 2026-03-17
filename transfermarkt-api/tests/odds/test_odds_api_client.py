"""
Tests for the Odds API client service.
All HTTP calls are mocked — no real API key needed.
"""
import pytest
from unittest.mock import patch, MagicMock

from app.services.odds_api.odds_api_client import (
    find_event,
    fetch_sharp_odds,
    extract_sharp_odds_from_event,
    resolve_sport_key,
    SHARP_BOOKMAKERS,
    SOCCER_SPORT_KEYS,
    TENNIS_SPORT_KEYS,
    SPORT_KEY_ALIASES,
)


# ── Sample API responses ─────────────────────────────────────────

SAMPLE_EVENTS_RESPONSE = [
    {
        "id": "event_001",
        "sport_key": "soccer_epl",
        "home_team": "Manchester United",
        "away_team": "Liverpool",
        "commence_time": "2026-03-10T20:00:00Z",
        "bookmakers": [],
    },
    {
        "id": "event_002",
        "sport_key": "soccer_epl",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "commence_time": "2026-03-10T17:30:00Z",
        "bookmakers": [],
    },
]

SAMPLE_EVENT_ODDS_RESPONSE = {
    "id": "event_001",
    "sport_key": "soccer_epl",
    "home_team": "Manchester United",
    "away_team": "Liverpool",
    "commence_time": "2026-03-10T20:00:00Z",
    "bookmakers": [
        {
            "key": "pinnacle",
            "title": "Pinnacle",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Manchester United", "price": 2.50},
                        {"name": "Liverpool", "price": 2.80},
                        {"name": "Draw", "price": 3.40},
                    ],
                }
            ],
        },
        {
            "key": "betfair_ex_eu",
            "title": "Betfair Exchange",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Manchester United", "price": 2.55},
                        {"name": "Liverpool", "price": 2.75},
                        {"name": "Draw", "price": 3.50},
                    ],
                }
            ],
        },
        {
            "key": "bet365",
            "title": "Bet365",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Manchester United", "price": 2.40},
                        {"name": "Liverpool", "price": 2.90},
                        {"name": "Draw", "price": 3.30},
                    ],
                }
            ],
        },
    ],
}


# ── Constants ─────────────────────────────────────────────────────

class TestConstants:
    def test_sharp_bookmakers_includes_pinnacle(self):
        assert "pinnacle" in SHARP_BOOKMAKERS

    def test_sharp_bookmakers_includes_betfair(self):
        assert "betfair_ex_eu" in SHARP_BOOKMAKERS

    def test_sharp_bookmakers_includes_betonline(self):
        assert "betonlineag" in SHARP_BOOKMAKERS

    def test_soccer_sport_keys_not_empty(self):
        assert len(SOCCER_SPORT_KEYS) > 0

    def test_soccer_sport_keys_includes_epl(self):
        assert "soccer_epl" in SOCCER_SPORT_KEYS

    def test_tennis_sport_keys_not_empty(self):
        assert len(TENNIS_SPORT_KEYS) > 0

    def test_tennis_sport_keys_includes_atp(self):
        assert "tennis_atp" in TENNIS_SPORT_KEYS

    def test_tennis_sport_keys_includes_wta(self):
        assert "tennis_wta" in TENNIS_SPORT_KEYS


# ── Sport key aliases ─────────────────────────────────────────────

class TestSportKeyAliases:
    def test_champions_league_resolves(self):
        assert resolve_sport_key("champions_league") == "soccer_uefa_champs_league"

    def test_la_liga_resolves(self):
        assert resolve_sport_key("la_liga") == "soccer_spain_la_liga"

    def test_epl_resolves(self):
        assert resolve_sport_key("epl") == "soccer_epl"

    def test_premier_league_resolves(self):
        assert resolve_sport_key("premier_league") == "soccer_epl"

    def test_atp_resolves(self):
        assert resolve_sport_key("atp") == "tennis_atp"

    def test_wta_resolves(self):
        assert resolve_sport_key("wta") == "tennis_wta"

    def test_raw_odds_api_key_passes_through(self):
        assert resolve_sport_key("soccer_epl") == "soccer_epl"

    def test_invalid_key_returns_none(self):
        assert resolve_sport_key("string") is None

    def test_none_returns_none(self):
        assert resolve_sport_key(None) is None

    def test_case_insensitive(self):
        assert resolve_sport_key("Champions_League") == "soccer_uefa_champs_league"

    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_find_event_accepts_alias(self, mock_httpx):
        """find_event should resolve 'champions_league' to the real key."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_EVENTS_RESPONSE
        mock_httpx.get.return_value = mock_response

        result = find_event(
            "fake_key", "Arsenal", "Chelsea",
            sport_key="champions_league",
        )
        # Verify it searched the correct resolved key
        call_url = mock_httpx.get.call_args[0][0]
        assert "soccer_uefa_champs_league" in call_url


# ── extract_sharp_odds_from_event ─────────────────────────────────

class TestExtractSharpOdds:
    def test_extracts_pinnacle_and_betfair(self):
        result = extract_sharp_odds_from_event(
            SAMPLE_EVENT_ODDS_RESPONSE,
            home_team="Manchester United",
            away_team="Liverpool",
        )
        assert "pinnacle" in result
        assert "betfair_ex_eu" in result
        # bet365 is NOT sharp — should be excluded
        assert "bet365" not in result

    def test_pinnacle_odds_correct(self):
        result = extract_sharp_odds_from_event(
            SAMPLE_EVENT_ODDS_RESPONSE,
            home_team="Manchester United",
            away_team="Liverpool",
        )
        pinnacle = result["pinnacle"]
        assert pinnacle["home"] == pytest.approx(2.50)
        assert pinnacle["away"] == pytest.approx(2.80)
        assert pinnacle["draw"] == pytest.approx(3.40)

    def test_betfair_odds_correct(self):
        result = extract_sharp_odds_from_event(
            SAMPLE_EVENT_ODDS_RESPONSE,
            home_team="Manchester United",
            away_team="Liverpool",
        )
        betfair = result["betfair_ex_eu"]
        assert betfair["home"] == pytest.approx(2.55)
        assert betfair["away"] == pytest.approx(2.75)
        assert betfair["draw"] == pytest.approx(3.50)

    def test_returns_empty_when_no_sharp_bookmakers(self):
        event_no_sharp = {
            "id": "event_001",
            "bookmakers": [
                {
                    "key": "bet365",
                    "title": "Bet365",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Team A", "price": 2.0},
                                {"name": "Team B", "price": 3.0},
                                {"name": "Draw", "price": 3.5},
                            ],
                        }
                    ],
                }
            ],
        }
        result = extract_sharp_odds_from_event(event_no_sharp, "Team A", "Team B")
        assert result == {}

    def test_returns_empty_when_no_bookmakers(self):
        event_empty = {"id": "event_001", "bookmakers": []}
        result = extract_sharp_odds_from_event(event_empty, "A", "B")
        assert result == {}

    def test_handles_missing_h2h_market(self):
        event = {
            "id": "event_001",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "title": "Pinnacle",
                    "markets": [
                        {
                            "key": "spreads",
                            "outcomes": [
                                {"name": "Team A", "price": 1.90},
                                {"name": "Team B", "price": 1.90},
                            ],
                        }
                    ],
                }
            ],
        }
        result = extract_sharp_odds_from_event(event, "Team A", "Team B")
        assert result == {}


# ── find_event ───────────────────────────────────────────────────

class TestFindEvent:
    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_finds_exact_match(self, mock_httpx):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_EVENTS_RESPONSE
        mock_httpx.get.return_value = mock_response

        result = find_event("fake_key", "Manchester United", "Liverpool", sport_key="soccer_epl")
        assert result is not None
        event_id, sport_key = result
        assert event_id == "event_001"
        assert sport_key == "soccer_epl"

    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_finds_fuzzy_match(self, mock_httpx):
        """Should match even with slightly different casing/spacing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_EVENTS_RESPONSE
        mock_httpx.get.return_value = mock_response

        result = find_event("fake_key", "manchester united", "liverpool", sport_key="soccer_epl")
        assert result is not None
        assert result[0] == "event_001"

    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_returns_none_when_no_match(self, mock_httpx):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_EVENTS_RESPONSE
        mock_httpx.get.return_value = mock_response

        result = find_event("fake_key", "FC Barcelona", "Real Madrid", sport_key="soccer_epl")
        assert result is None

    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_searches_multiple_leagues_when_no_sport_key(self, mock_httpx):
        """When sport_key is None, should search across SOCCER_SPORT_KEYS."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        # First league returns nothing, second returns the match
        mock_response.json.side_effect = [
            [],  # first league empty
            SAMPLE_EVENTS_RESPONSE,  # second league has the match
        ]
        mock_httpx.get.return_value = mock_response

        result = find_event("fake_key", "Arsenal", "Chelsea")
        assert result is not None
        assert result[0] == "event_002"

    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_handles_api_error_gracefully(self, mock_httpx):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"message": "Server Error"}
        mock_httpx.get.return_value = mock_response

        result = find_event("fake_key", "Manchester United", "Liverpool", sport_key="soccer_epl")
        assert result is None


# ── fetch_sharp_odds ─────────────────────────────────────────────

class TestFetchSharpOdds:
    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_returns_sharp_odds_dict(self, mock_httpx):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_EVENT_ODDS_RESPONSE
        mock_httpx.get.return_value = mock_response

        result = fetch_sharp_odds(
            "fake_key", "soccer_epl", "event_001",
            "Manchester United", "Liverpool",
        )
        assert "pinnacle" in result
        assert "betfair_ex_eu" in result
        assert "bet365" not in result

    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_returns_empty_on_api_error(self, mock_httpx):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"message": "Unauthorized"}
        mock_httpx.get.return_value = mock_response

        result = fetch_sharp_odds(
            "fake_key", "soccer_epl", "event_001",
            "Team A", "Team B",
        )
        assert result == {}

    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_returns_empty_on_exception(self, mock_httpx):
        mock_httpx.get.side_effect = Exception("Network error")

        result = fetch_sharp_odds(
            "fake_key", "soccer_epl", "event_001",
            "Team A", "Team B",
        )
        assert result == {}


# ── Tennis support ────────────────────────────────────────────────

SAMPLE_TENNIS_EVENTS = [
    {
        "id": "tennis_event_001",
        "sport_key": "tennis_wta",
        "home_team": "Eala A.",
        "away_team": "Noskova L.",
        "commence_time": "2026-03-11T02:00:00Z",
        "bookmakers": [],
    },
]

SAMPLE_TENNIS_ODDS_RESPONSE = {
    "id": "tennis_event_001",
    "sport_key": "tennis_wta",
    "home_team": "Eala A.",
    "away_team": "Noskova L.",
    "commence_time": "2026-03-11T02:00:00Z",
    "bookmakers": [
        {
            "key": "pinnacle",
            "title": "Pinnacle",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Eala A.", "price": 2.55},
                        {"name": "Noskova L.", "price": 1.55},
                    ],
                }
            ],
        },
        {
            "key": "betfair_ex_eu",
            "title": "Betfair Exchange",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Eala A.", "price": 2.60},
                        {"name": "Noskova L.", "price": 1.50},
                    ],
                }
            ],
        },
    ],
}


class TestTennisFindEvent:
    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_finds_tennis_event_by_sport(self, mock_httpx):
        """When sport='tennis', should search TENNIS_SPORT_KEYS."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_TENNIS_EVENTS
        mock_httpx.get.return_value = mock_response

        result = find_event("fake_key", "Eala A.", "Noskova L.", sport="tennis")
        assert result is not None
        event_id, sport_key = result
        assert event_id == "tennis_event_001"
        assert "tennis" in sport_key

    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_tennis_uses_tennis_keys_not_soccer(self, mock_httpx):
        """With sport='tennis', it should NOT search soccer sport keys."""
        call_args_list = []

        def fake_get(url, **kwargs):
            call_args_list.append(url)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = []
            return mock_resp

        mock_httpx.get.side_effect = fake_get

        find_event("fake_key", "Eala A.", "Noskova L.", sport="tennis")

        # Every URL searched should be a tennis sport key, not soccer
        for url in call_args_list:
            assert "tennis" in url
            assert "soccer" not in url

    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_soccer_still_uses_soccer_keys(self, mock_httpx):
        """Default (football) still searches soccer sport keys."""
        call_args_list = []

        def fake_get(url, **kwargs):
            call_args_list.append(url)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = []
            return mock_resp

        mock_httpx.get.side_effect = fake_get

        find_event("fake_key", "Manchester United", "Liverpool")

        for url in call_args_list:
            assert "soccer" in url

    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_invalid_sport_key_treated_as_none(self, mock_httpx):
        """Swagger placeholder 'string' should be treated as None — searches all keys."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_httpx.get.return_value = mock_response

        # Should not raise, should search the full list
        result = find_event("fake_key", "Team A", "Team B", sport_key="string")
        assert result is None  # no match, but didn't crash


class TestSingleTeamMatch:
    """When one team uses an abbreviation (e.g. PSG), single-team matching kicks in."""

    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_matches_when_one_team_is_abbreviated(self, mock_httpx):
        """Chelsea vs PSG: 'Chelsea' matches but 'PSG' doesn't match
        'Paris Saint Germain'. Single-team fallback should find the event."""
        events = [
            {
                "id": "ucl_event_001",
                "sport_key": "soccer_uefa_champs_league",
                "home_team": "Chelsea",
                "away_team": "Paris Saint Germain",
                "commence_time": "2026-03-17T19:00:00Z",
            },
        ]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = events
        mock_httpx.get.return_value = mock_response

        result = find_event(
            "fake_key", "Chelsea", "PSG",
            sport_key="soccer_uefa_champs_league",
        )
        assert result is not None
        assert result[0] == "ucl_event_001"

    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_no_match_when_multiple_events_match_one_team(self, mock_httpx):
        """If two events both have 'Chelsea', single-team match is ambiguous — skip."""
        events = [
            {
                "id": "event_1",
                "sport_key": "soccer_epl",
                "home_team": "Chelsea",
                "away_team": "Paris Saint Germain",
            },
            {
                "id": "event_2",
                "sport_key": "soccer_epl",
                "home_team": "Chelsea",
                "away_team": "Barcelona",
            },
        ]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = events
        mock_httpx.get.return_value = mock_response

        result = find_event(
            "fake_key", "Chelsea", "PSG",
            sport_key="soccer_epl",
        )
        # Ambiguous — two Chelsea events, should not match
        assert result is None

    @patch("app.services.odds_api.odds_api_client.httpx")
    def test_still_prefers_exact_match_over_single(self, mock_httpx):
        """Both-team match should take priority over single-team."""
        events = [
            {
                "id": "exact_match",
                "sport_key": "soccer_epl",
                "home_team": "Manchester United",
                "away_team": "Liverpool",
            },
        ]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = events
        mock_httpx.get.return_value = mock_response

        result = find_event(
            "fake_key", "Manchester United", "Liverpool",
            sport_key="soccer_epl",
        )
        assert result is not None
        assert result[0] == "exact_match"


class TestTennisExtractSharpOdds:
    def test_extracts_tennis_odds_no_draw(self):
        """Tennis events have no draw — home/away only."""
        result = extract_sharp_odds_from_event(
            SAMPLE_TENNIS_ODDS_RESPONSE,
            home_team="Eala A.",
            away_team="Noskova L.",
        )
        assert "pinnacle" in result
        assert "betfair_ex_eu" in result
        pinnacle = result["pinnacle"]
        assert pinnacle["home"] == pytest.approx(2.55)
        assert pinnacle["away"] == pytest.approx(1.55)
        assert "draw" not in pinnacle

    def test_tennis_sharp_odds_betfair_correct(self):
        result = extract_sharp_odds_from_event(
            SAMPLE_TENNIS_ODDS_RESPONSE,
            home_team="Eala A.",
            away_team="Noskova L.",
        )
        betfair = result["betfair_ex_eu"]
        assert betfair["home"] == pytest.approx(2.60)
        assert betfair["away"] == pytest.approx(1.50)


class TestExtractWithMismatchedNames:
    """When FlashScore names differ from Odds API names, fall back to API's own team names."""

    def test_extracts_using_api_team_names_when_flashscore_doesnt_match(self):
        """FlashScore says 'PSG' but outcome says 'Paris Saint Germain'."""
        event = {
            "id": "ucl_001",
            "home_team": "Chelsea",
            "away_team": "Paris Saint Germain",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "title": "Pinnacle",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Chelsea", "price": 2.15},
                                {"name": "Paris Saint Germain", "price": 2.80},
                                {"name": "Draw", "price": 3.50},
                            ],
                        }
                    ],
                }
            ],
        }
        result = extract_sharp_odds_from_event(event, "Chelsea", "PSG")
        assert "pinnacle" in result
        assert result["pinnacle"]["home"] == pytest.approx(2.15)
        assert result["pinnacle"]["away"] == pytest.approx(2.80)
        assert result["pinnacle"]["draw"] == pytest.approx(3.50)

    def test_extracts_tennis_with_different_name_format(self):
        """FlashScore: 'Eala A.' vs Odds API outcome: 'Alex Eala'."""
        event = {
            "id": "tennis_001",
            "home_team": "Alex Eala",
            "away_team": "Linda Noskova",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "title": "Pinnacle",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Alex Eala", "price": 2.55},
                                {"name": "Linda Noskova", "price": 1.55},
                            ],
                        }
                    ],
                }
            ],
        }
        result = extract_sharp_odds_from_event(event, "Eala A.", "Noskova L.")
        assert "pinnacle" in result
        assert result["pinnacle"]["home"] == pytest.approx(2.55)
        assert result["pinnacle"]["away"] == pytest.approx(1.55)
