"""Odds-movement → Telegram alert dispatcher.

Called from the per-match scrape job right after a new snapshot is persisted.
Pure-ish: all I/O (Redis reads, Telegram sends, DB lookups) is funnelled
through small async helpers so the threshold/dedupe logic can be unit-tested
without a live infrastructure.

Movement definition
-------------------
"Movement" is the absolute percentage change of an outcome's decimal odds
**vs the user's opening snapshot for that match**. Opening = the first
snapshot stored for that match in the current tracking session. This is
what bettors mean by "the line moved X% since open" — minute-to-minute
deltas are too noisy, and historical opens aren't meaningful once the user
stops tracking.

Why per-match-opening, not per-snapshot? Two reasons:
  1. Catches the full cumulative move (a slow 8% drift would never trigger
     a 5% threshold if compared snapshot-to-snapshot).
  2. Stable: a user setting "alert me at 5%" gets *one* notification per
     direction per market, not a stream as the line wobbles past 5%.

Dedupe
------
We store a Redis set ``telegram_alerted:{user_id}:{match_id}`` whose members
are ``{market}_{direction}`` (e.g. ``home_down``, ``away_up``). Once an
alert fires we add the member; we won't re-alert in the same direction.
Reverse-direction moves are independent and can still fire.

The set has a cooldown TTL — re-applied on every write — which means a
match that goes the whole tracking window without firing the second
direction will eventually let it fire again. For MVP this is fine; we can
tighten later.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterable, Optional

from app.models.markets import MARKET_1X2, label_for, outcomes_for
from app.services.odds_tracker.odds_tracker import odds_history_key
from app.services.telegram import bot_client
from app.settings import settings

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Pure logic — easy to unit-test
# ────────────────────────────────────────────────────────────────────

# Legacy alias — historically these were the only "markets" the dispatcher
# knew about (the outcome keys on a 1X2 snapshot). Kept exported so any
# external caller (e.g. tests) still works.
FOOTBALL_MARKETS = ("home", "draw", "away")
TENNIS_MARKETS = ("player1", "player2")


def markets_for_sport(sport: str, market: str = MARKET_1X2) -> tuple[str, ...]:
    """Return the outcome keys present on a snapshot for (sport, market).

    Tennis stays on its existing 1X2 shape; football routes through the
    central markets registry so adding O/U 3.5 or BTTS later is just a
    registry entry, not a dispatcher change.
    """
    if sport == "tennis":
        return TENNIS_MARKETS
    return outcomes_for(market)


@dataclass(frozen=True)
class MovementBreach:
    """A single market that has crossed the user's threshold."""
    market: str  # e.g. "home", "player1"
    direction: str  # "up" | "down"
    opening_odds: float
    current_odds: float
    abs_pct_move: float  # absolute % change vs opening

    @property
    def dedupe_key(self) -> str:
        return f"{self.market}_{self.direction}"


def compute_breaches(
    opening: dict,
    current: dict,
    sport: str,
    threshold_pct: float,
    market: str = MARKET_1X2,
) -> list[MovementBreach]:
    """Return every outcome whose abs % change from opening to current
    exceeds ``threshold_pct``. Robust against missing keys / zero opens.

    ``market`` selects which outcome keys to look at on the snapshots
    (e.g. for ``ou_2.5`` we diff ``over``/``under`` rather than 1X2 keys).
    Defaults to 1X2 so legacy callers behave identically.
    """
    if threshold_pct <= 0:
        return []
    breaches: list[MovementBreach] = []
    for outcome in markets_for_sport(sport, market):
        op = opening.get(outcome)
        cu = current.get(outcome)
        if op is None or cu is None:
            continue
        try:
            op_f = float(op)
            cu_f = float(cu)
        except (TypeError, ValueError):
            continue
        if op_f <= 0:
            # Decimal odds <= 0 is nonsense; refuse to divide.
            continue
        pct = ((cu_f - op_f) / op_f) * 100.0
        if abs(pct) >= threshold_pct:
            breaches.append(MovementBreach(
                market=outcome,
                direction="up" if pct > 0 else "down",
                opening_odds=op_f,
                current_odds=cu_f,
                abs_pct_move=round(abs(pct), 2),
            ))
    return breaches


def format_alert_message(
    *,
    home_team: Optional[str],
    away_team: Optional[str],
    sport: str,
    breaches: Iterable[MovementBreach],
    bookmaker: Optional[str],
    threshold_pct: float,
    market: str = MARKET_1X2,
) -> str:
    """Render the Telegram message body. HTML parse mode, kept short
    because users will see this on a phone lock-screen.

    Header includes the market label (e.g. "Over/Under 2.5") so the user
    sees at a glance which line moved — useful when one match is tracked
    across multiple markets.
    """
    if sport == "tennis":
        title = f"<b>{home_team or 'P1'} vs {away_team or 'P2'}</b>"
    else:
        title = f"<b>{home_team or 'Home'} vs {away_team or 'Away'}</b>"

    pretty = {
        "home": "Home",
        "draw": "Draw",
        "away": "Away",
        "player1": home_team or "Player 1",
        "player2": away_team or "Player 2",
        "over": "Over",
        "under": "Under",
    }
    arrows = {"up": "▲", "down": "▼"}

    lines = [
        title,
        f"<i>{label_for(market)} · threshold ±{threshold_pct:g}% from opening</i>",
        "",
    ]
    for b in breaches:
        lines.append(
            f"{arrows[b.direction]} {pretty.get(b.market, b.market)}: "
            f"{b.opening_odds:.2f} → <b>{b.current_odds:.2f}</b> "
            f"({'+' if b.direction == 'up' else '-'}{b.abs_pct_move}%)"
        )
    if bookmaker:
        lines.append("")
        lines.append(f"<i>Source: {bookmaker}</i>")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────
# I/O helpers
# ────────────────────────────────────────────────────────────────────

def _alerted_set_key(user_id: str, match_id: str, market: str) -> str:
    """Dedupe set key, scoped per (user, match, market) so an O/U breach
    doesn't dedupe a later 1X2 breach on the same match.

    The 1X2 key keeps its legacy shape (no market suffix) so dedupe state
    persisted before the multi-market rollout still applies — avoids a
    spam burst on the first scrape after deploy.
    """
    if market == MARKET_1X2:
        return f"telegram_alerted:{user_id}:{match_id}"
    return f"telegram_alerted:{user_id}:{match_id}:{market}"


async def _get_opening_snapshot(
    redis_client, match_id: str, market: str = MARKET_1X2,
) -> Optional[dict]:
    """First snapshot in Redis history for this (match, market). Returns
    None if the history is empty (e.g. we're processing the very first
    scrape and haven't appended yet — caller should skip).
    """
    raw = await redis_client.lindex(odds_history_key(match_id, market), 0)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def _already_alerted(
    redis_client, user_id: str, match_id: str, market: str, dedupe_key: str,
) -> bool:
    return bool(await redis_client.sismember(
        _alerted_set_key(user_id, match_id, market), dedupe_key,
    ))


async def _mark_alerted(
    redis_client, user_id: str, match_id: str, market: str, dedupe_key: str,
) -> None:
    key = _alerted_set_key(user_id, match_id, market)
    await redis_client.sadd(key, dedupe_key)
    # Re-apply TTL on every write so an actively-moving match doesn't drop
    # the dedupe state mid-game.
    await redis_client.expire(key, settings.TELEGRAM_ALERT_COOLDOWN_SECONDS)


# ────────────────────────────────────────────────────────────────────
# Public entry point
# ────────────────────────────────────────────────────────────────────

async def maybe_dispatch_alert(
    *,
    redis_client,
    match_id: str,
    new_snapshot: dict,
    match_meta: dict,
    sport: str,
    market: str = MARKET_1X2,
) -> None:
    """Best-effort alert delivery. Never raises into the caller.

    ``match_meta`` is the dict stored under ``tracked_match:<id>`` in Redis;
    it carries ``user_id``, ``home_team``, ``away_team`` etc.

    ``market`` scopes the opening lookup and the dedupe key so a user
    tracking both 1X2 and O/U gets one alert per (market, outcome,
    direction) rather than cross-talk between markets.
    """
    try:
        user_id = match_meta.get("user_id")
        if not user_id:
            # Legacy tracked match with no owner — nothing to do.
            logger.debug("maybe_dispatch_alert: match=%s has no user_id in meta — skipping.", match_id)
            return

        # Lookup the user's Telegram prefs from Postgres. Cheap (single PK
        # lookup); we don't cache because the user can toggle alerts off
        # at any time and we want that to take effect immediately.
        prefs = _load_user_prefs(user_id)
        if not prefs or not prefs.enabled:
            # _load_user_prefs already logged the specific reason at INFO level.
            return

        opening = await _get_opening_snapshot(redis_client, match_id, market=market)
        if opening is None:
            logger.debug(
                "maybe_dispatch_alert: user=%s match=%s market=%s — no opening snapshot yet.",
                user_id, match_id, market,
            )
            return
        if opening.get("timestamp") == new_snapshot.get("timestamp"):
            # First-ever snapshot for this market — no movement to detect yet.
            logger.debug(
                "maybe_dispatch_alert: user=%s match=%s market=%s — first snapshot, no movement yet.",
                user_id, match_id, market,
            )
            return

        breaches = compute_breaches(
            opening=opening,
            current=new_snapshot,
            sport=sport,
            threshold_pct=prefs.threshold_pct,
            market=market,
        )
        logger.info(
            "maybe_dispatch_alert: user=%s match=%s market=%s threshold=%.1f%% — "
            "%d breach(es): %s",
            user_id, match_id, market, prefs.threshold_pct,
            len(breaches), [(b.dedupe_key, b.abs_pct_move) for b in breaches],
        )
        if not breaches:
            return

        # Dedupe — drop any breach whose (market, outcome, direction)
        # already fired within the cooldown window.
        fresh: list[MovementBreach] = []
        for b in breaches:
            if not await _already_alerted(
                redis_client, user_id, match_id, market, b.dedupe_key,
            ):
                fresh.append(b)
        if not fresh:
            logger.info(
                "maybe_dispatch_alert: user=%s match=%s market=%s — all breaches already alerted (dedupe), skipping.",
                user_id, match_id, market,
            )
            return

        msg = format_alert_message(
            home_team=match_meta.get("home_team"),
            away_team=match_meta.get("away_team"),
            sport=sport,
            breaches=fresh,
            bookmaker=new_snapshot.get("bookmaker"),
            threshold_pct=prefs.threshold_pct,
            market=market,
        )
        sent = await bot_client.send_message(prefs.chat_id, msg)
        if sent:
            for b in fresh:
                await _mark_alerted(
                    redis_client, user_id, match_id, market, b.dedupe_key,
                )
            logger.info(
                "Dispatched Telegram alert: user=%s match=%s market=%s breaches=%s",
                user_id, match_id, market, [b.dedupe_key for b in fresh],
            )
        else:
            logger.warning(
                "Telegram send failed; will retry on next scrape: user=%s match=%s market=%s",
                user_id, match_id, market,
            )
    except Exception as e:
        # We MUST NOT let an alerting bug crash the scrape job.
        logger.exception("maybe_dispatch_alert crashed: %s", e)


# ────────────────────────────────────────────────────────────────────
# User-prefs loader (kept here so the call site stays one import)
# ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _UserAlertPrefs:
    chat_id: str
    threshold_pct: float
    enabled: bool


def _load_user_prefs(user_id: str) -> Optional[_UserAlertPrefs]:
    """Synchronous Postgres lookup. Called from inside the async scrape job
    but the SQLAlchemy session is sync — cheap enough that we don't need
    to push it to a thread pool. If profiling shows it as hot, wrap with
    ``run_in_executor``.
    """
    try:
        from app.models.database import SessionLocal
        from app.models.users import User
        session = SessionLocal()
        try:
            user = session.query(User).filter(User.id == user_id).one_or_none()
            if user is None:
                logger.warning("Telegram prefs: no user row for user_id=%s", user_id)
                return None
            if not user.telegram_chat_id:
                logger.info(
                    "Telegram prefs: user=%s has no telegram_chat_id — "
                    "complete the /link flow first.",
                    user_id,
                )
                return None
            if not user.telegram_alerts_enabled:
                logger.info(
                    "Telegram prefs: user=%s alerts disabled — "
                    "PATCH /telegram/preferences {\"enabled\": true} to activate.",
                    user_id,
                )
                return None
            if user.telegram_alert_threshold_pct is None:
                logger.info(
                    "Telegram prefs: user=%s has no threshold configured — "
                    "PATCH /telegram/preferences {\"threshold_pct\": N} to set it.",
                    user_id,
                )
                return None
            if user.role not in ("premium", "admin"):
                logger.info(
                    "Telegram prefs: user=%s role=%s is not premium/admin — skipping.",
                    user_id, user.role,
                )
                return None
            logger.info(
                "Telegram prefs: user=%s chat_id=...%s threshold=%.1f%%",
                user_id, user.telegram_chat_id[-4:], user.telegram_alert_threshold_pct,
            )
            return _UserAlertPrefs(
                chat_id=user.telegram_chat_id,
                threshold_pct=float(user.telegram_alert_threshold_pct),
                enabled=True,
            )
        finally:
            session.close()
    except Exception as e:
        logger.warning("Telegram prefs lookup failed for user %s: %s", user_id, e)
        return None
