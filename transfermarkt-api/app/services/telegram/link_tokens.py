"""One-time tokens for the Telegram deep-link flow.

The flow:
  1. Authenticated user hits POST /api/telegram/link.
  2. We mint a random token and store ``link_token:<token> -> <user_id>``
     in Redis with a short TTL (10 min by default).
  3. Frontend opens ``t.me/<bot>?start=<token>``.
  4. User taps "Start" in Telegram; bot receives ``/start <token>`` as a
     message. Our webhook handler calls :func:`consume_link_token`, gets
     the user_id, and writes the chat_id onto the User row.

Tokens are single-use: consume_link_token deletes the key. This means even
if a token leaks (e.g. a user pastes it in a public chat), at most one
account gets linked.

We store tokens in Redis rather than Postgres because:
  - They have a natural TTL (Redis handles expiry).
  - Volume is low but write churn is high (mint on every link click).
  - Losing tokens on a Redis restart just forces the user to click "link"
    again — no data lost.
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional

from app.settings import settings

logger = logging.getLogger(__name__)

# 32 bytes -> 43-char URL-safe string. Enough entropy that brute-forcing
# a valid token within the 10-minute TTL is not feasible.
_TOKEN_BYTES = 32


def _key(token: str) -> str:
    return f"telegram_link_token:{token}"


async def create_link_token(redis_client, user_id: str) -> str:
    """Mint a token mapping to ``user_id`` and return it. TTL controlled by
    ``settings.TELEGRAM_LINK_TOKEN_TTL_SECONDS``.

    Caller is responsible for serialising ``user_id`` to a string (UUID
    objects must be cast first).
    """
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    await redis_client.set(
        _key(token),
        str(user_id),
        ex=settings.TELEGRAM_LINK_TOKEN_TTL_SECONDS,
    )
    logger.info("Minted Telegram link token for user_id=%s", user_id)
    return token


async def consume_link_token(redis_client, token: str) -> Optional[str]:
    """Atomically read-and-delete the token. Returns the bound user_id, or
    ``None`` if the token is unknown / already consumed / expired.

    Uses GETDEL so two concurrent ``/start`` calls (e.g. user double-taps)
    can't both succeed.
    """
    raw = await redis_client.getdel(_key(token))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    logger.info("Consumed Telegram link token for user_id=%s", raw)
    return raw
