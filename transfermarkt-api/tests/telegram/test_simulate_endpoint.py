"""Tests for the POST /telegram/simulate endpoint handler.

We exercise the route function directly (rather than going through
fastapi.TestClient + dependency_overrides) so the test stays consistent
with the rest of the suite, which tests handlers against in-memory
fixtures + patches on the side-effecting boundaries.

What matters:
  - Admins can simulate; non-admins (including premium) get 403.
  - The synthetic snapshot we build genuinely produces a breach at the
    requested pct + direction + outcome.
  - The message body that lands on the wire carries the SIMULATED banner
    so a recipient can't confuse it with a real alert.
  - The response payload reports the same numbers the dispatcher saw.
  - A Telegram delivery failure (bot blocked etc.) surfaces as a 502.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.endpoints.telegram import SimulateAlertRequest, simulate_alert


class _StubUser:
    """Just enough of the User model to drive the handler."""
    def __init__(self, *, role="admin", chat_id="987654321"):
        self.role = role
        self.telegram_chat_id = chat_id
        # Other columns the handler doesn't read but the model would carry:
        self.id = "00000000-0000-0000-0000-000000000001"
        self.email = "qa@example.com"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Auth gates ────────────────────────────────────────────────────

class TestAuthGates:
    def test_non_admin_premium_user_is_rejected(self):
        user = _StubUser(role="premium")
        with pytest.raises(HTTPException) as exc:
            _run(simulate_alert(SimulateAlertRequest(), user))
        # 403 — admin-only because simulate bypasses the user's own
        # configured threshold and dedupe state.
        assert exc.value.status_code == 403

    def test_normal_user_is_rejected(self):
        user = _StubUser(role="normal")
        with pytest.raises(HTTPException) as exc:
            _run(simulate_alert(SimulateAlertRequest(), user))
        assert exc.value.status_code == 403

    def test_admin_without_linked_chat_is_rejected(self):
        user = _StubUser(role="admin", chat_id=None)
        with pytest.raises(HTTPException) as exc:
            _run(simulate_alert(SimulateAlertRequest(), user))
        assert exc.value.status_code == 400


# ── Happy path ────────────────────────────────────────────────────

class TestSimulationProducesBreach:
    @pytest.fixture
    def mock_send(self):
        """Patch bot_client.send_message at the handler's import site so
        no real HTTPS calls go out during the test.
        """
        with patch(
            "app.api.endpoints.telegram.bot_client.send_message",
            new_callable=AsyncMock,
        ) as m:
            m.return_value = True
            yield m

    def test_default_request_is_20_pct_down_on_home(self, mock_send):
        user = _StubUser(role="admin")
        result = _run(simulate_alert(SimulateAlertRequest(), user))

        # Endpoint manufactured 2.00 → 1.60 (down 20%) on home.
        assert result.delivered is True
        assert result.market == "1x2"
        assert result.outcome == "home"
        assert result.direction == "down"
        assert result.pct == 20.0
        assert result.opening_odds == 2.00
        assert result.current_odds == 1.60

        # send_message called once with the chat_id and the full message.
        mock_send.assert_awaited_once()
        chat_id, body = mock_send.await_args.args
        assert chat_id == "987654321"
        assert body == result.message

    def test_message_carries_simulated_banner(self, mock_send):
        """A recipient must be able to tell this apart from a real alert."""
        user = _StubUser(role="admin")
        result = _run(simulate_alert(SimulateAlertRequest(), user))

        assert "SIMULATED ALERT" in result.message
        # The dispatcher's own formatting must still be present, otherwise
        # we'd be testing a different code path than production.
        assert "1X2 Full Time" in result.message
        assert "Real Madrid vs Barcelona" in result.message
        assert "▼" in result.message  # down arrow for direction="down"
        assert "2.00" in result.message and "1.60" in result.message

    def test_up_direction_inflates_odds(self, mock_send):
        user = _StubUser(role="admin")
        result = _run(simulate_alert(
            SimulateAlertRequest(pct=15.0, direction="up", outcome="away"),
            user,
        ))
        # 2.00 * 1.15 = 2.30
        assert result.current_odds == 2.30
        assert result.direction == "up"
        assert result.outcome == "away"
        assert "▲" in result.message

    def test_over_under_market(self, mock_send):
        user = _StubUser(role="admin")
        result = _run(simulate_alert(
            SimulateAlertRequest(
                pct=25.0,
                direction="down",
                market="ou_2.5",
                outcome="over",
            ),
            user,
        ))
        assert result.market == "ou_2.5"
        assert result.outcome == "over"
        assert "Over/Under 2.5" in result.message
        # 2.00 * 0.75 = 1.50
        assert result.current_odds == 1.50


# ── Validation ────────────────────────────────────────────────────

class TestValidation:
    @pytest.fixture
    def mock_send(self):
        with patch(
            "app.api.endpoints.telegram.bot_client.send_message",
            new_callable=AsyncMock,
        ) as m:
            m.return_value = True
            yield m

    def test_outcome_not_valid_for_market_is_400(self, mock_send):
        # "over" only exists on the ou_2.5 market, not on 1x2.
        user = _StubUser(role="admin")
        with pytest.raises(HTTPException) as exc:
            _run(simulate_alert(
                SimulateAlertRequest(market="1x2", outcome="over"),
                user,
            ))
        assert exc.value.status_code == 400
        # No Telegram call made when validation fails.
        mock_send.assert_not_called()

    def test_tennis_player_outcomes_are_accepted(self, mock_send):
        user = _StubUser(role="admin")
        result = _run(simulate_alert(
            SimulateAlertRequest(
                sport="tennis",
                home_team="Alcaraz",
                away_team="Sinner",
                outcome="player1",
            ),
            user,
        ))
        assert result.outcome == "player1"
        assert result.delivered is True


# ── Delivery failures ─────────────────────────────────────────────

class TestDeliveryFailure:
    def test_send_failure_surfaces_as_502(self):
        with patch(
            "app.api.endpoints.telegram.bot_client.send_message",
            new_callable=AsyncMock,
        ) as mock_send:
            mock_send.return_value = False  # Telegram refused
            user = _StubUser(role="admin")
            with pytest.raises(HTTPException) as exc:
                _run(simulate_alert(SimulateAlertRequest(), user))
            # Caller must know delivery failed — same UX as /test.
            assert exc.value.status_code == 502
