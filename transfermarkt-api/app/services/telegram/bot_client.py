"""Thin async wrapper over the Telegram Bot HTTP API.

We deliberately avoid pulling in a heavyweight library (python-telegram-bot)
because we only need two calls (sendMessage, setWebhook) and adding another
dependency that pins httpx/asyncio is more pain than it's worth.

All callers must be async — the FastAPI app is async end-to-end and the
scrape job runs on an APScheduler AsyncIOScheduler.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"


def _api_url(method: str) -> str:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured. Cannot talk to the Telegram API."
        )
    return f"{_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"


async def send_message(
    chat_id: str,
    text: str,
    *,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
    timeout: float = 10.0,
) -> bool:
    """DM ``text`` to ``chat_id``. Returns True on success, False on any failure
    (we never raise into the scrape job — alert delivery is best-effort).

    HTML is the default parse mode because it's strictly more permissive than
    MarkdownV2 (no need to escape ``.``, ``-``, ``!``, ``(``, ``)`` etc) and
    our alert templates are simple enough not to need Markdown.
    """
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(_api_url("sendMessage"), json=payload)
        if resp.status_code == 200 and resp.json().get("ok"):
            return True
        logger.warning(
            "Telegram sendMessage failed: status=%s body=%s",
            resp.status_code, resp.text[:300],
        )
        return False
    except Exception as e:
        # Network blips, DNS, bot blocked by user — none of these should
        # bring down the scrape job.
        logger.warning("Telegram sendMessage exception: %s", e)
        return False


async def set_webhook(url: str, secret_token: Optional[str] = None) -> bool:
    """Register ``url`` as the webhook target. Telegram echoes ``secret_token``
    back in the ``X-Telegram-Bot-Api-Secret-Token`` header — we use that in
    the webhook handler to reject forged calls.

    Idempotent — Telegram lets you re-set the webhook URL at any time.
    """
    payload: dict = {
        "url": url,
        "allowed_updates": ["message"],
        "drop_pending_updates": True,
    }
    if secret_token:
        payload["secret_token"] = secret_token
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_api_url("setWebhook"), json=payload)
        if resp.status_code == 200 and resp.json().get("ok"):
            logger.info("Telegram webhook registered: %s", url)
            return True
        logger.error(
            "Telegram setWebhook failed: status=%s body=%s",
            resp.status_code, resp.text[:300],
        )
        return False
    except Exception as e:
        logger.error("Telegram setWebhook exception: %s", e)
        return False


def build_deep_link(token: str) -> str:
    """Return the ``t.me/<bot>?start=<token>`` URL the user clicks to link."""
    if not settings.TELEGRAM_BOT_USERNAME:
        raise RuntimeError(
            "TELEGRAM_BOT_USERNAME is not configured — cannot build deep-link."
        )
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={token}"
