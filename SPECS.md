# Sharper Bets — Project Specification

A SaaS betting-analysis platform that tracks live football/tennis odds, detects
significant line movements, computes Dixon-Coles match predictions, surfaces
arbitrage opportunities, and pushes real-time Telegram alerts to premium users.

- **Backend:** `transfermarkt-api/` — Python / FastAPI
- **Frontend:** `frontend-bet/` — Next.js (TypeScript)
- **Brand name in API:** "Sharper Bets"

---

## 1. System Architecture

```
                       ┌──────────────────────────┐
                       │  Next.js frontend (80)    │
                       │  dashboard / arbitrage /  │
                       │  pro-analysis / auth      │
                       └────────────┬─────────────┘
                                    │ Firebase JWT
                                    ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI backend  (Cloud Run, europe-west9, port 9000)        │
│                                                                │
│  /competitions /clubs /players   ← Transfermarkt scrapers      │
│  /odds                            ← live odds tracking         │
│  /predictions                     ← Dixon-Coles model          │
│  /telegram                        ← alert wiring + webhook      │
│  /billing                         ← LemonSqueezy webhooks       │
│  /users  /waitlist  /admin/*      ← account + ops              │
│                                                                │
│  APScheduler (in-process) → per-match scrape jobs every N min  │
└───────┬───────────────────────┬──────────────────┬───────────┘
        │                       │                  │
        ▼                       ▼                  ▼
   ┌─────────┐           ┌────────────┐      ┌──────────────┐
   │ Redis   │           │ PostgreSQL │      │ External APIs │
   │ (GCE VM)│           │ (GCE VM)   │      │ The Odds API  │
   │ live    │           │ durable    │      │ FlashScore    │
   │ state + │           │ snapshots, │      │ (Selenium)    │
   │ history │           │ results    │      │ Firebase      │
   └─────────┘           └────────────┘      │ Telegram Bot  │
                                             └──────────────┘
```

- **Cloud Run** runs the stateless FastAPI app.
- **GCE VM** hosts Redis + PostgreSQL + a separate Selenium scraper service
  (`docker-compose.gce.yml`), reached by Cloud Run over a VPC connector.
- **Firebase** handles auth (JWT) and the Firestore waitlist collection.

---

## 2. Backend (`transfermarkt-api/`)

### 2.1 Entry point — `main.py`
- Initializes FastAPI, Firebase Admin SDK (credentials from GCP Secret Manager
  in prod, or `GOOGLE_APPLICATION_CREDENTIALS` locally), and APScheduler.
- On startup, **recovers tracked-match jobs** from Redis with staggered delays
  (1.5s × index) and re-schedules each at its per-row poll cadence (read from
  PostgreSQL). Also recovers pending result-polling jobs.
- Root logging is configured at **INFO** level (`logging.basicConfig`).

### 2.2 API routing — `app/api/api.py`
All routers are mounted under `/api`:

| Prefix | Purpose |
|---|---|
| `/competitions`, `/clubs`, `/players` | Transfermarkt scraping |
| `/odds` | Live odds tracking (track/stop/history/SSE stream) |
| `/predictions` | Dixon-Coles match-outcome probabilities |
| `/users` | Account/profile |
| `/billing` | LemonSqueezy subscription webhooks |
| `/telegram` | Telegram alert linking, preferences, webhook, simulate |
| `/admin/dixon-coles` | Model data + training management (admin) |
| `/admin` | Platform dashboard — users, tracking load, Odds API spend (admin) |
| `/waitlist` | Firestore waitlist collection |

API docs: `http://localhost:9000/api/docs`

### 2.3 Key services (`app/services/`)

- **`flashscore_scraper/`** — Selenium/Chromium scraper for live 1X2 odds and
  lineups from FlashScore. Free (no API credits). Source of the displayed
  home/draw/away (and tennis player1/player2) odds.
- **`odds_api/odds_api_client.py`** — The Odds API client. Provides sharp-book
  overlay (Pinnacle/Betfair via `h2h`), Over/Under totals, event commence-time
  refresh, and final scores. All outbound calls go through `_counted_get`,
  which bumps Redis usage counters. **See §6 for the credit-cost model.**
- **`odds_tracker/`** — APScheduler jobs (`odds_scheduler.py`), Redis storage
  (`odds_tracker.py`), and PostgreSQL persistence (`snapshot_persistence.py`).
- **`dixon_coles/`** — statistical match-outcome model.
- **`arbitrage/`** — arbitrage detection.
- **`telegram/`** — alert dispatcher, bot client, deep-link token management.
- **`clubs/`, `competitions/`, `players/`** — Transfermarkt web scrapers.

### 2.4 Auth & rate limiting
- **Auth:** Firebase JWT verified in `app/core/auth.py`; protected endpoints use
  `Depends(get_current_user)`. Admin-only endpoints use `require_role("admin")`.
- **Roles:** `normal` | `premium` | `admin` (plain string column, no enum).
  Admin counts as premium for feature gating.
- **Rate limiting:** dual — slowapi (per-IP) + Redis per-user/endpoint counting.
  Controlled by `RATE_LIMITING_ENABLE` (default `false`).

---

## 3. Data Model

### 3.1 PostgreSQL tables

**`users`** (`app/models/users.py`)
| Column | Notes |
|---|---|
| `id` (UUID, PK) | one row per Firebase UID, created lazily |
| `firebase_uid` (unique) | |
| `email` | |
| `role` | `normal` / `premium` / `admin` |
| `lemonsqueezy_customer_id`, `lemonsqueezy_subscription_id`, `subscription_status`, `current_period_end` | billing state |
| `telegram_chat_id` | set after deep-link `/start` flow |
| `telegram_alerts_enabled` (bool, default **false**) | must be explicitly toggled on |
| `telegram_alert_threshold_pct` (float, nullable) | absolute % move vs opening that triggers an alert |

**`tracked_matches`** (`app/models/odds_models.py`)
- `match_id` (unique), `sport`, `home_team`, `away_team`, `start_time(_raw)`,
  `status` (`tracking`/`completed`), `tracked_since`.
- `odds_api_event_id`, `odds_api_sport_key` — Odds API mapping (set at track time).
- `user_id` (FK → users, indexed) — owner.
- `poll_interval_seconds` — per-tier cadence baked on the row for restart recovery.
- `markets` (JSON text, e.g. `["1x2","ou_2.5"]`; NULL ⇒ `["1x2"]`).

**`odds_snapshots`**
- `match_id` (indexed), `sport`, `timestamp`, `market` (default `1x2`, indexed).
- 1X2: `home`/`draw`/`away`; tennis: `player1`/`player2`; totals: `over`/`under`/`line`.
- `bookmaker` — primary book (FlashScore-scraped for 1X2, e.g. Betclic).
- `sharp_odds` (JSON text, nullable) — Odds API sharp books (Pinnacle/Betfair).
  **NULL when the Odds API call failed/was out of quota** — this is the gap you
  see in the chart when sharp data stops while Betclic continues.
- Indexes: `(match_id, id)` and `(match_id, market, id)` for ordered history.

**`match_results`**
- One row per `match_id`. Created (with `completed=False`) when pre-match
  tracking stops at kickoff; filled by the result-poller.
- `home_score`, `away_score`, `outcome` (`home`/`draw`/`away` or `p1`/`p2`),
  `completed`, `result_source` (`odds_api`/`timeout`), `poll_attempts`.

### 3.2 Redis keys
| Key | Shape | Purpose |
|---|---|---|
| `tracked_match:<id>` | JSON | match metadata (incl. `user_id`, `markets`) |
| `tracked_matches_index` | set | active tracker IDs (used by startup recovery) |
| `odds_history:<id>` | list | 1X2 snapshots (legacy/no suffix) |
| `odds_history:<id>:<market>` | list | other markets (e.g. `:ou_2.5`) |
| `telegram_alerted:<user>:<match>[:<market>]` | set | alert dedupe (TTL = cooldown) |
| Odds API usage counters | int | lifetime + per-day call counts |

### 3.3 Markets registry (`app/models/markets.py`)
Single source of truth, consumed by scraper, scheduler, dispatcher, frontend.

| Market id | Label | Outcomes | Line |
|---|---|---|---|
| `1x2` | 1X2 Full Time | home, draw, away | — |
| `ou_2.5` | Over/Under 2.5 | over, under | 2.5 |

Adding a market = append id + outcomes here, teach the scraper to fetch it;
the rest of the system flows through generically.

---

## 4. Odds Tracking Pipeline

1. **Track** (`POST /api/odds/track`) — stamps `user_id`, per-tier
   `poll_interval_seconds`, and the chosen `markets` onto the match meta;
   maps the match to an Odds API event when possible; schedules an APScheduler
   job. Tennis is forced to 1X2-only. Non-1X2 markets require an Odds API event
   mapping or they're silently dropped (and the response warns the user).
2. **Scrape job** (`odds_scheduler.make_scrape_job`), every cycle:
   - Refreshes kickoff time (Odds API `commence_time` if mapped, else FlashScore).
   - Stops the tracker `STOP_BEFORE_KICKOFF_SECONDS` before kickoff and hands off
     to the result poller.
   - For each configured market: 1X2 → FlashScore scrape; O/U → Odds API totals.
   - Fetches sharp-book overlay (Odds API `h2h`) for 1X2 only.
   - Stores a snapshot to Redis (`rpush`) + PostgreSQL (best-effort, threaded).
   - Calls `maybe_dispatch_alert(...)` per market.
3. **Result polling** — after kickoff, polls Odds API scores until the match is
   `completed` or the poll budget is exhausted (`timeout`).

History is exposed via `/api/odds/history/<match_id>` and a live SSE stream;
both enforce per-user ownership (404 if not the owner).

---

## 5. Telegram Alerts

### 5.1 Movement model
"Movement" = absolute % change of an outcome's decimal odds **vs the opening
snapshot for that match+market** (first snapshot in the current tracking
session). Catches cumulative drift and yields one alert per
(market, outcome, direction) rather than a stream as the line wobbles.

```
pct = ((current_odds - opening_odds) / opening_odds) × 100
breach if abs(pct) >= user.threshold_pct
```

### 5.2 Endpoints (`app/api/endpoints/telegram.py`)
| Method | Path | Access | Purpose |
|---|---|---|---|
| POST | `/api/telegram/link` | premium | mint a one-time t.me deep-link |
| POST | `/api/telegram/unlink` | auth | disconnect chat, disable alerts |
| GET | `/api/telegram/status` | auth | linked? enabled? threshold? |
| POST | `/api/telegram/test` | premium | send a hardcoded test DM |
| POST | `/api/telegram/simulate` | **admin** | run synthetic snapshots through the real dispatcher |
| PATCH | `/api/telegram/preferences` | premium | set `threshold_pct` / `enabled` |
| POST | `/api/telegram/webhook` | public (header-guarded) | receive `/start <token>` |

### 5.3 Activation prerequisites (all required)
An alert only fires when **all** of these hold (`_load_user_prefs`):
1. user row exists, 2. `telegram_chat_id` set (deep-link completed),
3. **`telegram_alerts_enabled = true`**, 4. `telegram_alert_threshold_pct` set,
5. role ∈ {premium, admin}.

> ⚠️ The `/start` webhook deliberately **does not** flip `telegram_alerts_enabled`.
> The user must explicitly `PATCH /preferences {"enabled": true}` after setting a
> threshold. A common "no alerts" cause is `enabled = false` while everything
> else looks correct.

> ⚠️ `POST /simulate` bypasses `_load_user_prefs` (only checks `chat_id` + admin),
> so a working simulation does **not** prove alerts are enabled for the real
> scheduler path.

### 5.4 Dedupe
Redis set `telegram_alerted:<user>:<match>[:<market>]` with members
`{outcome}_{direction}` (e.g. `draw_down`). TTL = `TELEGRAM_ALERT_COOLDOWN_SECONDS`
(default 3600s), re-applied on every write. Reverse-direction moves fire
independently.

### 5.5 Observability
`maybe_dispatch_alert` and `_load_user_prefs` log the specific reason an alert
did/didn't fire at **INFO** (so it's visible in Cloud Run): prefs-not-ready
reasons, breach counts with per-outcome %, dedupe skips, and dispatch success.

---

## 6. The Odds API — Credit-Cost Model ⚠️

The Odds API does **not** charge 1 credit per call. For the odds endpoints:

```
credits per call = (number of markets) × (number of regions)
```

Per scrape cycle, per match. The columns show the **original** cost and the
cost **after the quota fix** (`regions="eu"` + sharp overlay throttled to every
`SHARP_ODDS_EVERY_N_CYCLES`th cycle, default 3):

| Call | Endpoint | markets | regions | Was | Now |
|---|---|---|---|---|---|
| Sharp 1X2 overlay (`fetch_sharp_odds`) | `/events/{id}/odds` | `h2h` (1) | eu (1) | 2 | **~0.33** (1 every 3rd cycle) |
| Over/Under (`fetch_totals_odds`) | `/events/{id}/odds` | `totals` (1) | eu (1) | 2 | **1** |
| Kickoff refresh (`get_event_commence_time`) | `/events` (list) | — | — | 0 | **0** (free) |

Per-cycle burn for a match tracking both markets dropped from **4 → ~1.33
credits** (≈3× less); a 1X2-only match dropped from **2 → ~0.33** (≈6× less).
Tunable via `ODDS_API_REGIONS` and `SHARP_ODDS_EVERY_N_CYCLES`.

**Key facts**
- The displayed 1X2 odds come from **FlashScore (free)** — the Odds API `h2h`
  call is only the **sharp overlay**.
- Sharp (`h2h`) and O/U (`totals`) are **two separate HTTP calls**, not one.
  Tracking O/U **doubles** the per-cycle burn (2 → 4 credits).
- The app's internal usage counter (`/admin/info` → `odds_api.calls_total`)
  counts **HTTP requests**, not credits, so it **undercounts** real spend.

**Burn rate** — one match, both markets, at a 10-minute cadence:
```
4 credits × 6 cycles/hr × 24 hr ≈ 576 credits/day
```
The free tier is **500/month**, so a single overnight tracker exhausts the
monthly quota in well under a day. Symptom: sharp odds (Pinnacle/Betfair) stop
while Betclic (FlashScore) continues; the failing call logs
`Odds API event odds returned 401` (401 = `OUT_OF_USAGE_CREDITS` or `INVALID_KEY`).

**Cost levers (largest first)**
1. ✅ **Done** — `regions="eu"` (configurable via `ODDS_API_REGIONS`) halves every call.
2. ✅ **Done** — sharp overlay throttled to every `SHARP_ODDS_EVERY_N_CYCLES`th
   cycle (default 3), decoupled from the FlashScore loop. The primary line and
   any explicitly-tracked market still refresh every cycle.
3. Lengthen the poll cadence (per-tier in `app/core/quotas.py`).
4. Combining `markets=h2h,totals` into one call does **not** save credits
   (still markets×regions); it only saves HTTP round-trips.

**Still a business decision:** the free tier is 500 credits/month. Even at the
reduced burn, several concurrent trackers (World Cup scenario) will need a
**paid Odds API plan**. Paying customers seeing sharp data cut out mid-match is
a churn event — provision quota for expected concurrency before launch. The key
is already env-driven (`ODDS_API_KEY`), so upgrading is a key swap + redeploy.

---

## 7. Frontend (`frontend-bet/`)

Next.js (TypeScript). Pages in `src/app/`: `dashboard`, `arbitrage`,
`pro-analysis`, `auth`. Firebase client config in `src/lib/firebaseConfig.ts`;
auth context in `src/contexts/`; UI components in `src/components/`.

---

## 8. Infrastructure & Deployment

- **Local dev:** `docker-compose.yml` — fastapi (9000), redis (6379), frontend (80).
- **Production:**
  - FastAPI → **GCP Cloud Run** (europe-west9), service `fastapi-app`.
  - Redis + PostgreSQL + Selenium scraper → **GCE VM** via `docker-compose.gce.yml`,
    reached over a VPC connector.
  - Firebase credentials in **GCP Secret Manager** (`firebase-credentials`).
- **CI/CD:** `.github/workflows/deploy.yml` deploys on push to `master` when
  `transfermarkt-api/**` changes (Artifact Registry → Cloud Run).
  `cloudbuild.yaml` is an alternative pipeline. GCP auth via Workload Identity
  Federation.

### Inspecting production
```bash
# Logs (structured — use jsonPayload, not textPayload)
gcloud logging read \
  'resource.type="cloud_run_revision"
   AND resource.labels.service_name="fastapi-app"
   AND jsonPayload.message=~"(?i)telegram"' \
  --project=YOUR_PROJECT_ID --freshness=2h --limit=200 \
  --format='table(timestamp,jsonPayload.message)'

# PostgreSQL (psql inside the container on the GCE VM)
gcloud compute ssh <vm-name> --zone=europe-west9-a --tunnel-through-iap \
  --command="docker exec -it postgres psql -U postgres -d betting_analysis"

# Odds API remaining quota (free endpoint, costs nothing)
curl -s -i "https://api.the-odds-api.com/v4/sports/?apiKey=KEY" | grep -i x-requests
```

---

## 9. Configuration (env vars)

Set in `transfermarkt-api/.env`:

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Firebase service-account JSON (local) |
| `GCP_PROJECT_ID` | — | GCP project (prod — Secret Manager) |
| `REDIS_HOST` | `localhost` | Redis host (GCE VM internal IP in prod) |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/betting_analysis` | PostgreSQL DSN |
| `ODDS_API_KEY` | — | The Odds API key (sharp odds + totals + scores) |
| `RATE_LIMITING_ENABLE` | `false` | enable rate limiting |
| `RATE_LIMITING_FREQUENCY` | `2/3seconds` | slowapi limit string |
| `DEFAULT_MAX_REQUESTS` | `50` | per-user request quota per period |
| `DEFAULT_RESET_DURATION` | `86400` | quota reset (seconds) |
| `TELEGRAM_BOT_TOKEN` | `""` | from @BotFather |
| `TELEGRAM_BOT_USERNAME` | `""` | bot username, no `@` |
| `TELEGRAM_WEBHOOK_SECRET` | `""` | shared secret for webhook guard |
| `TELEGRAM_PUBLIC_BASE_URL` | `""` | base URL for deep-link/webhook |
| `TELEGRAM_ALERT_COOLDOWN_SECONDS` | `3600` | dedupe TTL (same-direction re-alert) |
| `TELEGRAM_MIN_THRESHOLD_PCT` | `1.0` | min user-settable threshold |
| `TELEGRAM_MAX_THRESHOLD_PCT` | `50.0` | max user-settable threshold |
| `TELEGRAM_LINK_TOKEN_TTL_SECONDS` | `600` | deep-link token expiry |

CI/CD secrets: `GCP_PROJECT_ID`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`.

---

## 10. Testing & Git Workflow

- **Tests:** pytest in `transfermarkt-api/tests/` (uses `schema` for response
  validation, `unittest.mock` for patching scrapers).
  `pytest` / `pytest tests/<dir>/` / `pytest tests/<file>::<test>`.
- **Branching:** never commit to `master`. Use `feature/…`, `fix/…`, `refactor/…`;
  open a PR into `master`. Merging to `master` triggers a production deploy when
  `transfermarkt-api/**` changes.
