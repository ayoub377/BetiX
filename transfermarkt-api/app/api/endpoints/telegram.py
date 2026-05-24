"""Telegram alert API.

Endpoints:

  POST  /api/telegram/link           (auth, premium) — mint deep-link
  POST  /api/telegram/unlink         (auth)          — disconnect chat
  GET   /api/telegram/status         (auth)          — current wiring
  PATCH /api/telegram/preferences    (auth, premium) — set threshold/toggle
  POST  /api/telegram/webhook        (public)        — receives bot updates,
                                                       guarded by header secret

The webhook is intentionally public (Telegram calls it from their servers)
but rejects any request whose ``X-Telegram-Bot-Api-Secret-Token`` header
does not match ``TELEGRAM_WEBHOOK_SECRET``. That secret is set when we
register the webhook URL with Telegram and travels with every update.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import redis_client
from app.models.database import get_db
from app.models.users import User
from app.services.telegram import bot_client, link_tokens
from app.settings import settings

router = APIRouter()
logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def _require_premium(user: User) -> None:
    """Premium-only gate. Admin counts as premium for testing."""
    if user.role not in ("premium", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Telegram alerts are a Pro feature. Upgrade to enable.",
        )


def _validate_threshold(pct: float) -> float:
    lo = settings.TELEGRAM_MIN_THRESHOLD_PCT
    hi = settings.TELEGRAM_MAX_THRESHOLD_PCT
    if pct < lo or pct > hi:
        raise HTTPException(
            status_code=400,
            detail=f"Threshold must be between {lo}% and {hi}%.",
        )
    return float(pct)


# ────────────────────────────────────────────────────────────────────
# Schemas
# ────────────────────────────────────────────────────────────────────

class LinkResponse(BaseModel):
    deep_link: str
    expires_in_seconds: int


class StatusResponse(BaseModel):
    linked: bool
    alerts_enabled: bool
    threshold_pct: Optional[float] = None
    # Surfaced so the dashboard can show "Linked as @username (chat ...456)"
    chat_id_suffix: Optional[str] = None


class PreferencesUpdate(BaseModel):
    threshold_pct: Optional[float] = Field(
        default=None,
        description="Absolute % move from opening odds at which to alert.",
    )
    enabled: Optional[bool] = None


class SimulateAlertRequest(BaseModel):
    """Knobs for /telegram/simulate — every field has a sensible default
    so the endpoint can be called with an empty body to mean "send me a
    20% drop on the home outcome of a fake match."
    """
    pct: float = Field(
        default=20.0,
        ge=1.0,
        le=99.0,
        description="Absolute % move to simulate. The endpoint manufactures "
        "opening + current snapshots whose ratio yields this exact pct.",
    )
    direction: str = Field(
        default="down",
        description="'down' (odds shorten — favourite firmed up) or "
        "'up' (odds drift — value appeared).",
        pattern="^(up|down)$",
    )
    market: str = Field(
        default="1x2",
        description="Market id (see app.models.markets). '1x2' or 'ou_2.5'.",
    )
    outcome: str = Field(
        default="home",
        description="Which outcome on the chosen market the simulated "
        "move lands on (e.g. 'home', 'over').",
    )
    sport: str = Field(default="football", pattern="^(football|tennis)$")
    home_team: str = Field(default="Real Madrid")
    away_team: str = Field(default="Barcelona")


class SimulateAlertResponse(BaseModel):
    """Returned to the caller so they can confirm the pipeline worked
    even before they look at Telegram. ``message`` is the exact body
    that was posted — useful for screenshotting in bug reports.
    """
    delivered: bool
    chat_id_suffix: str
    market: str
    outcome: str
    direction: str
    opening_odds: float
    current_odds: float
    pct: float
    message: str


# ────────────────────────────────────────────────────────────────────
# Routes — authenticated user surface
# ────────────────────────────────────────────────────────────────────

@router.post("/link", response_model=LinkResponse)
async def create_link(user: User = Depends(get_current_user)) -> LinkResponse:
    """Mint a one-time token and return the t.me deep-link.

    Frontend should open this URL in a new tab; Telegram handles the rest.
    """
    _require_premium(user)
    if not settings.TELEGRAM_BOT_USERNAME or not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Telegram integration is not configured on the server.",
        )
    token = await link_tokens.create_link_token(redis_client, str(user.id))
    return LinkResponse(
        deep_link=bot_client.build_deep_link(token),
        expires_in_seconds=settings.TELEGRAM_LINK_TOKEN_TTL_SECONDS,
    )


@router.post("/unlink")
async def unlink(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Disconnect Telegram. Disables alerts so the user isn't surprised by
    a re-link auto-resuming notifications under an old threshold.
    """
    user_in_db = db.query(User).filter(User.id == user.id).one()
    user_in_db.telegram_chat_id = None
    user_in_db.telegram_alerts_enabled = False
    db.commit()
    return {"ok": True}


@router.get("/status", response_model=StatusResponse)
async def status(user: User = Depends(get_current_user)) -> StatusResponse:
    chat_id = user.telegram_chat_id
    return StatusResponse(
        linked=bool(chat_id),
        alerts_enabled=bool(user.telegram_alerts_enabled and chat_id),
        threshold_pct=user.telegram_alert_threshold_pct,
        chat_id_suffix=chat_id[-4:] if chat_id else None,
    )


@router.post("/test")
async def send_test_alert(user: User = Depends(get_current_user)) -> dict:
    """DM a confirmation message to the user's linked Telegram chat.

    Purpose: lets the user verify end-to-end delivery (token correct,
    chat_id correct, bot not blocked) without waiting for an actual
    odds movement. Premium-only because Free users can't link in the
    first place — defensive check kept anyway.
    """
    _require_premium(user)
    if not user.telegram_chat_id:
        raise HTTPException(
            status_code=400,
            detail="Link your Telegram account before sending a test alert.",
        )

    ok = await bot_client.send_message(
        user.telegram_chat_id,
        "✅ <b>Test alert from Sharper Bets</b>\n\n"
        "If you can read this, your Telegram connection is working. "
        "You'll get a DM here whenever a tracked match's odds move past "
        "your threshold.",
    )
    if not ok:
        # Most common cause: user blocked the bot. Telling them lets the
        # support burden drop to zero.
        raise HTTPException(
            status_code=502,
            detail=(
                "Telegram refused the message. Make sure you haven't blocked "
                "@%s, then try again." % (settings.TELEGRAM_BOT_USERNAME or "the bot",)
            ),
        )
    return {"ok": True}


@router.post("/simulate", response_model=SimulateAlertResponse)
async def simulate_alert(
    payload: SimulateAlertRequest = SimulateAlertRequest(),
    user: User = Depends(get_current_user),
) -> SimulateAlertResponse:
    """Send a real alert through the dispatcher pipeline against synthetic
    snapshots — same code path as a production breach, just with hand-crafted
    inputs.

    Why this exists vs ``/test``: ``/test`` only proves the bot client can
    talk to Telegram with a hardcoded string. It does NOT exercise
    ``compute_breaches`` or ``format_alert_message``, so a bug in the
    detection logic or message template would slip past it. ``/simulate``
    builds an (opening, current) snapshot pair guaranteed to produce a
    breach of the requested ``pct`` on the requested outcome, then runs
    those snapshots through the real dispatcher helpers and dispatches
    via the same ``bot_client.send_message`` used in production.

    Admin-only (not just premium) because it bypasses the user's
    configured threshold and dedupe state — handy for QA, dangerous if
    exposed broadly. The user's own ``telegram_chat_id`` is still the
    delivery target, so you only spam yourself.
    """
    # Admin-only — see docstring.
    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Simulation is admin-only. Use POST /telegram/test for a "
            "non-simulated delivery check.",
        )
    if not user.telegram_chat_id:
        raise HTTPException(
            status_code=400,
            detail="Link your Telegram account before running a simulation.",
        )

    # Lazy import so the endpoint module stays cheap to import in tests.
    from app.models.markets import is_supported, outcomes_for
    from app.services.telegram.alert_dispatcher import (
        compute_breaches,
        format_alert_message,
    )

    if not is_supported(payload.market):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown market '{payload.market}'.",
        )
    valid_outcomes = outcomes_for(payload.market)
    # Tennis uses a separate outcome key set (player1/player2) handled
    # inside the dispatcher; allow either path through.
    if payload.sport == "tennis":
        valid_outcomes = ("player1", "player2")
    if payload.outcome not in valid_outcomes:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Outcome '{payload.outcome}' not valid for "
                f"market='{payload.market}' sport='{payload.sport}'. "
                f"Expected one of: {list(valid_outcomes)}."
            ),
        )

    # Construct opening + current snapshots whose ratio on ``outcome``
    # yields exactly ``pct`` in the requested direction. Start opening at
    # 2.00 because a coin-flip line is the most intuitive baseline for
    # the resulting "from 2.00 to X" message.
    opening_odds = 2.00
    multiplier = 1.0 + (payload.pct / 100.0) if payload.direction == "up" \
        else 1.0 - (payload.pct / 100.0)
    current_odds = round(opening_odds * multiplier, 2)

    opening_snapshot: dict = {outcome: opening_odds for outcome in valid_outcomes}
    current_snapshot: dict = {outcome: opening_odds for outcome in valid_outcomes}
    current_snapshot[payload.outcome] = current_odds

    # Threshold one tick below the simulated pct so the breach computation
    # always fires (avoids edge-case rounding around an exact-match threshold).
    threshold_pct = max(1.0, payload.pct - 0.5)
    breaches = compute_breaches(
        opening=opening_snapshot,
        current=current_snapshot,
        sport=payload.sport,
        threshold_pct=threshold_pct,
        market=payload.market,
    )
    if not breaches:
        # Should never happen given how we constructed the snapshots —
        # but if it does, surfacing a 500 rather than silently sending
        # nothing makes the bug obvious.
        raise HTTPException(
            status_code=500,
            detail="Internal error: synthetic snapshot produced no breaches.",
        )

    msg = format_alert_message(
        home_team=payload.home_team,
        away_team=payload.away_team,
        sport=payload.sport,
        breaches=breaches,
        bookmaker="(simulated)",
        threshold_pct=threshold_pct,
        market=payload.market,
    )

    # Prepend a banner so the recipient cannot confuse this with a
    # genuine production alert — important when an admin is testing
    # against a chat they also use for real notifications.
    banner = (
        "🧪 <b>SIMULATED ALERT</b> — triggered by /telegram/simulate.\n"
        "Not a real odds movement.\n\n"
    )
    full_msg = banner + msg

    delivered = await bot_client.send_message(user.telegram_chat_id, full_msg)
    if not delivered:
        # Same advice as /test — most common cause is bot blocked.
        raise HTTPException(
            status_code=502,
            detail=(
                "Telegram refused the message. Make sure you haven't blocked "
                "@%s, then try again." % (settings.TELEGRAM_BOT_USERNAME or "the bot",)
            ),
        )

    return SimulateAlertResponse(
        delivered=True,
        chat_id_suffix=user.telegram_chat_id[-4:],
        market=payload.market,
        outcome=payload.outcome,
        direction=payload.direction,
        opening_odds=opening_odds,
        current_odds=current_odds,
        pct=payload.pct,
        message=full_msg,
    )


@router.patch("/preferences", response_model=StatusResponse)
async def update_preferences(
    payload: PreferencesUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatusResponse:
    _require_premium(user)
    user_in_db = db.query(User).filter(User.id == user.id).one()

    if payload.threshold_pct is not None:
        user_in_db.telegram_alert_threshold_pct = _validate_threshold(payload.threshold_pct)

    if payload.enabled is not None:
        if payload.enabled and not user_in_db.telegram_chat_id:
            raise HTTPException(
                status_code=400,
                detail="Link your Telegram account before enabling alerts.",
            )
        if payload.enabled and user_in_db.telegram_alert_threshold_pct is None:
            raise HTTPException(
                status_code=400,
                detail="Set a threshold % before enabling alerts.",
            )
        user_in_db.telegram_alerts_enabled = payload.enabled

    db.commit()
    db.refresh(user_in_db)
    return StatusResponse(
        linked=bool(user_in_db.telegram_chat_id),
        alerts_enabled=bool(
            user_in_db.telegram_alerts_enabled and user_in_db.telegram_chat_id
        ),
        threshold_pct=user_in_db.telegram_alert_threshold_pct,
        chat_id_suffix=user_in_db.telegram_chat_id[-4:] if user_in_db.telegram_chat_id else None,
    )


# ────────────────────────────────────────────────────────────────────
# Webhook — public, header-guarded
# ────────────────────────────────────────────────────────────────────

@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> dict:
    """Handle incoming Telegram updates. We only care about the
    ``/start <token>`` message that completes the deep-link flow.

    Returning 200 with ``{ok: true}`` to *every* legitimate call (even ones
    we ignore) — Telegram retries on non-2xx, and we don't want it
    hammering us for messages we don't process.
    """
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        # Fail closed: better to drop updates than to accept forged ones.
        logger.error("Webhook hit but TELEGRAM_WEBHOOK_SECRET is unset.")
        raise HTTPException(status_code=503, detail="Webhook not configured.")

    if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
        # Don't leak whether the secret was wrong or missing.
        raise HTTPException(status_code=401, detail="Unauthorized.")

    update = await request.json()
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if not chat_id or not text.startswith("/start"):
        return {"ok": True}

    # ``/start <token>`` — Telegram includes the deep-link payload after the slash.
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await bot_client.send_message(
            str(chat_id),
            "Welcome! To finish linking, open the dashboard and click "
            "<b>Connect Telegram</b> again.",
        )
        return {"ok": True}

    token = parts[1].strip()
    user_id = await link_tokens.consume_link_token(redis_client, token)
    if not user_id:
        await bot_client.send_message(
            str(chat_id),
            "This link has expired. Please go back to the dashboard and "
            "click <b>Connect Telegram</b> to get a fresh link.",
        )
        return {"ok": True}

    user = db.query(User).filter(User.id == user_id).one_or_none()
    if user is None:
        logger.warning("Webhook: token consumed but user_id=%s not found.", user_id)
        return {"ok": True}

    user.telegram_chat_id = str(chat_id)
    # We don't flip alerts_enabled on automatically — the user still has to
    # set a threshold and toggle alerts from the dashboard. Keeps the
    # default-off principle for any pushed messages.
    db.commit()

    await bot_client.send_message(
        str(chat_id),
        "✅ <b>Telegram connected.</b>\n\n"
        "Head back to the dashboard, set your alert threshold %, and "
        "enable notifications. You'll get a DM here whenever a tracked "
        "match's odds move past your threshold.",
    )
    return {"ok": True}
