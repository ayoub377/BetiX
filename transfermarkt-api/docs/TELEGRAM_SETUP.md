# Telegram Alerts — Operator Setup

The Telegram bot delivers odds-movement alerts to Pro users. This document
covers the one-time bot creation, env var configuration, webhook
registration, and a manual smoke-test.

## What users see

1. In the dashboard, a Pro user clicks **Connect Telegram**.
2. We open `https://t.me/<YourBot>?start=<one-time-token>` in a new tab.
3. They tap **Start** in Telegram; the bot DMs them "✅ Connected".
4. Back in the dashboard, they set their threshold % (default suggestion: 5%)
   and toggle **Alerts enabled**.
5. From then on, whenever any match they're tracking moves ≥ threshold %
   (in either direction) on any 1X2/2-way market vs the opening odds for
   that match, they get a DM. Each `(match, market, direction)` fires at
   most once per match within a 60-min cooldown window.

## One-time setup

### 1. Create the bot

1. Open Telegram, search `@BotFather`, send `/newbot`.
2. Pick a display name (e.g. "Sharper Bets Alerts").
3. Pick a username ending in `bot` (e.g. `SharperBetsAlertsBot`). Save the
   bot token BotFather replies with — that's `TELEGRAM_BOT_TOKEN`.
4. (Optional) `/setdescription`, `/setabouttext`, `/setuserpic` for polish.
5. **Disable group access** with `/setjoingroups → Disable` — alerts are
   1:1 DMs only, no need to let it join groups.
6. **Disable privacy mode** is NOT required since we only respond to
   `/start <token>`. Leave it at the default (enabled).

### 2. Generate a webhook secret

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Save the output as `TELEGRAM_WEBHOOK_SECRET`. Telegram will echo this back
to us on every webhook call in the `X-Telegram-Bot-Api-Secret-Token`
header, so we can reject forged updates.

### 3. Env vars

Add to `.env` (and to GCP Secret Manager / Cloud Run env for production):

```env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...      # from BotFather
TELEGRAM_BOT_USERNAME=SharperBetsAlertsBot  # no @, exact case
TELEGRAM_WEBHOOK_SECRET=<your-secret>
TELEGRAM_PUBLIC_BASE_URL=https://api.sharperbets.com
# Optional tuning (defaults in app/settings.py):
# TELEGRAM_ALERT_COOLDOWN_SECONDS=3600
# TELEGRAM_MIN_THRESHOLD_PCT=1.0
# TELEGRAM_MAX_THRESHOLD_PCT=50.0
# TELEGRAM_LINK_TOKEN_TTL_SECONDS=600
```

Restart the API for these to take effect.

### 4. Register the webhook with Telegram

Once the API is deployed at a public HTTPS URL, register it (one-shot —
Telegram persists the registration):

```bash
curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "'"${TELEGRAM_PUBLIC_BASE_URL}"'/api/telegram/webhook",
    "secret_token": "'"${TELEGRAM_WEBHOOK_SECRET}"'",
    "allowed_updates": ["message"],
    "drop_pending_updates": true
  }'
```

Expected response: `{"ok":true,"result":true,"description":"Webhook was set"}`.

To inspect or clear:

```bash
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/deleteWebhook"
```

> **Local dev:** Telegram requires HTTPS for webhooks. Use `ngrok http 9000`
> or `cloudflared tunnel` to expose your local API, then register that URL.
> Remember to re-register when you switch back to prod.

## Smoke test (no real users needed)

1. As an admin or premium user, call:
   ```bash
   curl -X POST https://api.sharperbets.com/api/telegram/link \
     -H "Authorization: Bearer <firebase-jwt>"
   ```
   Should return `{"deep_link": "https://t.me/.../?start=...", "expires_in_seconds": 600}`.

2. Open the `deep_link` in a browser → Telegram opens → tap **Start**. You
   should receive "✅ Telegram connected." within ~1 second.

3. Set a low threshold so any move triggers:
   ```bash
   curl -X PATCH https://api.sharperbets.com/api/telegram/preferences \
     -H "Authorization: Bearer <firebase-jwt>" \
     -H "Content-Type: application/json" \
     -d '{"threshold_pct": 1.0, "enabled": true}'
   ```

4. Start tracking a live match via `POST /api/odds/track`. After the second
   scrape cycle (when opening + current snapshots both exist) you should
   get a DM if odds moved ≥ 1%.

## Common operational issues

| Symptom | Cause | Fix |
|---|---|---|
| `/api/telegram/link` returns 503 | `TELEGRAM_BOT_TOKEN` or `TELEGRAM_BOT_USERNAME` unset | Set env vars + restart |
| `/api/telegram/webhook` returns 503 | `TELEGRAM_WEBHOOK_SECRET` unset | Set env var + restart |
| `/api/telegram/webhook` returns 401 | Telegram is sending updates with a stale secret (you rotated it but didn't re-register) | Re-run `setWebhook` |
| User taps "Start" but never gets confirmation | Token expired (10-min TTL) or webhook URL unreachable | Check `getWebhookInfo.last_error_message`; user clicks link again |
| Alerts never fire even though odds moved | User isn't premium, or alerts not enabled, or threshold too high | `GET /api/telegram/status` to inspect |
| Same alert fires repeatedly | Dedupe key cleared (Redis restart, match unregistered) | Expected behaviour after restart; reduce noise by raising cooldown |
| Bot blocked by user | They blocked the bot in Telegram | We log + drop the send; no retry. They must `/start` again |

## How alerts are computed

For each new odds snapshot of a tracked match:

1. Look up the owning user (`tracked_matches.user_id`).
2. Skip unless they are `premium`/`admin`, have a linked `chat_id`, alerts
   are enabled, and a `threshold_pct` is set.
3. Load the **opening snapshot** for this match from Redis
   (`odds_history:<match_id>[0]`).
4. For each 1X2 market (or `player1`/`player2` for tennis), compute
   `((current − opening) / opening) * 100`.
5. If `|pct| ≥ threshold_pct`, emit a `MovementBreach{market, direction}`.
6. Filter out breaches we've already alerted on (Redis set
   `telegram_alerted:<user_id>:<match_id>`).
7. Send a single combined DM listing all fresh breaches; record the
   dedupe keys with a 60-min sliding TTL.

All of step 4–5 is in `app/services/telegram/alert_dispatcher.py` as
`compute_breaches` — pure function, fully unit-tested.
