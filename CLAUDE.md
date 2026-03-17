# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A SaaS betting analysis platform with two main components:
- **`transfermarkt-api/`** — Python/FastAPI backend that scrapes Transfermarkt data, tracks live odds, computes Dixon-Coles predictions, and detects arbitrage opportunities
- **`frontend-bet/`** — Next.js frontend (TypeScript) for the user-facing dashboard


## Architecture

### Backend (`transfermarkt-api/`)

**Entry point:** `main.py` — initializes FastAPI, Firebase Admin SDK (credentials fetched from GCP Secret Manager in production or via `GOOGLE_APPLICATION_CREDENTIALS` env var locally), APScheduler, and Redis-based odds tracking recovery on startup.

**API routing:** `app/api/api.py` registers all routers under `/api`:
- `/competitions`, `/clubs`, `/players` — Transfermarkt scraping endpoints
- `/odds` — Live odds tracking
- `/arbitrage` — Arbitrage opportunity detection
- `/predictions` — Dixon-Coles match outcome predictions
- `/waitlist` — Firestore waitlist collection

**Key services (`app/services/`):**
- `flashscore_scraper/` — Selenium-based scraper (Chromium) for live match odds and lineups scraping from FlashScore
- `odds_tracker/` — APScheduler jobs that poll odds every 20 minutes, store in Redis; jobs are recovered on restart with staggered delays
- `dixon_coles/` — Statistical model for match outcome probabilities
- `arbitrage/` — Arbitrage detection logic
- `clubs/`, `competitions/`, `players/` — Transfermarkt web scrapers

**Auth:** Firebase JWT tokens verified via `app/core/auth.py`. All protected endpoints use `Depends(get_current_user)`.

**Rate limiting:** Dual system — slowapi (per-IP) + Redis-based per-user/endpoint counting. Controlled by `RATE_LIMITING_ENABLE` env var (default: `false`).

**Config:** `app/settings.py` uses pydantic-settings; Redis host via `REDIS_HOST` env var (defaults to `localhost`).

### Frontend (`frontend-bet/`)

Next.js app with pages in `src/app/`: `dashboard`, `arbitrage`, `pro-analysis`, `auth`. Firebase client config in `src/lib/firebaseConfig.ts`. Auth context in `src/contexts/`. UI components in `src/components/`.

### Infrastructure

- **Local dev:** `docker-compose.yml` — fastapi (port 9000), redis (6379), frontend (port 80)
- **Production:** GCP Cloud Run (europe-west9) for FastAPI; GCE VM with `docker-compose.gce.yml` for Redis + PostgreSQL. CI/CD in `.github/workflows/deploy.yml` deploys on push to `master` when `transfermarkt-api/**` changes (Artifact Registry → Cloud Run)
- Firebase credentials stored in GCP Secret Manager as `firebase-credentials` secret
- Cloud Build config in `cloudbuild.yaml` (alternative to GitHub Actions pipeline)

## Running Locally

### Backend

```bash
cd transfermarkt-api

# With Poetry
poetry shell
poetry install --no-root
export PYTHONPATH=$PYTHONPATH:$(pwd)
python main.py  # runs on port 9000

# Or with pip
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 9000 --reload
```

API docs: http://localhost:9000/api/docs

### Full stack via Docker Compose

```bash
docker-compose up --build
```

### Frontend

```bash
cd frontend-bet
npm install   # or yarn / pnpm
npm run dev
```

## Testing

Tests are in `transfermarkt-api/tests/` using pytest:

```bash
cd transfermarkt-api
pytest                          # run all tests
pytest tests/clubs/             # run a specific test directory
pytest tests/clubs/test_clubs_profile.py  # run a single file
```

Tests use `schema` library for response validation and `unittest.mock` for patching scrapers.

## Required Environment Variables

Set in `transfermarkt-api/.env`:

| Variable | Description |
|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to Firebase service account JSON (local dev) |
| `REDIS_HOST` | Redis host (default: `localhost`, set to GCE VM internal IP in production) |
| `DATABASE_URL` | PostgreSQL connection string (default: `postgresql://postgres:postgres@localhost:5432/betting_analysis`) |
| `GCP_PROJECT_ID` | GCP project ID (production only — used to fetch secrets from Secret Manager) |
| `RATE_LIMITING_ENABLE` | Enable rate limiting (`true`/`false`, default `false`) |
| `RATE_LIMITING_FREQUENCY` | slowapi rate limit string (default `2/3seconds`) |
| `DEFAULT_MAX_REQUESTS` | Per-user request quota per period (default `50`) |
| `DEFAULT_RESET_DURATION` | Quota reset period in seconds (default `86400`) |

GCP credentials for CI/CD are configured via Workload Identity Federation. GitHub Actions secrets needed: `GCP_PROJECT_ID`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`.

## Git Branching Strategy

Always work on a dedicated branch — never commit directly to `master`.

### Branch naming conventions

| Type | Format | Example |
|---|---|---|
| Feature | `feature/<short-description>` | `feature/add-live-scores` |
| Bug fix | `fix/<short-description>` | `fix/odds-tracker-crash` |
| Refactor | `refactor/<short-description>` | `refactor/cleanup-auth` |

### Workflow

1. **Branch off master:** `git checkout master && git pull && git checkout -b feature/my-feature`
2. **Commit often** with clear messages
3. **Push your branch:** `git push origin feature/my-feature`
4. **Open a Pull Request** on GitHub to merge into `master`
5. **After merge**, delete the branch locally and remotely

### Important

- The CI/CD pipeline (`.github/workflows/deploy.yml`) deploys on push to `master` when `transfermarkt-api/**` changes — so merging to master triggers a production deploy.
- Always test locally before merging.