# Observability — Grafana Cloud + Loki

Single searchable source of truth for **all** application logs: the Cloud Run
backend (`fastapi-app`), the Cloud Run frontend (`frontend-app`), and the GCE
VM containers (Redis, Postgres, scraper-service).

```
 Cloud Run  fastapi-app ─┐
            frontend-app ─┤ Cloud Logging sink → Pub/Sub topic → subscription
                          │                                          │
 GCE VM     redis         │                                          ▼
            postgres      │                                   ┌──────────────┐
            scraper       ├── Docker socket ───────────────►  │ Grafana Alloy │
                          │                                   │  (on the VM)  │
                          │                                   └──────┬───────┘
                          └──────────────────────────────────────────┘
                                                                     ▼
                                                          Grafana Cloud (Loki)
                                                          search · dashboards · alerts
```

Why this shape: both Cloud Run services already emit to Cloud Logging, so we
**route** those logs out via a sink rather than instrumenting each service. One
Alloy agent on the VM is the only moving part we run.

---

## What the app already does

- **Backend structured logs** — when `JSON_LOGS=true`, the backend emits one
  JSON object per log line (see `transfermarkt-api/app/core/logging_config.py`)
  with `severity`, `logger`, and a `component` label
  (`odds` / `scraper` / `auth` / `payments` / `telegram` / `predictions` / `api`).
  Cloud Run parses these into structured entries automatically.
- **Odds API call logging** — every Odds API request logs one line with
  `event=odds_api_call` and `oddsapi_status`, so call volume and 401s are
  queryable without touching Redis.

---

## One-time setup

Set your project once:

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="europe-west9"
```

### 1. Grafana Cloud credentials

Create a free Grafana Cloud stack (<https://grafana.com/auth/sign-up/create-user>),
then from **Connections → Add new connection → Hosted logs (Loki)** copy:

- the **push URL** (e.g. `https://logs-prod-012.grafana.net/loki/api/v1/push`)
- the **User** (a numeric instance ID)
- an **API token** with scope `logs:write` (Account → Access Policies)

### 2. GCP Pub/Sub topic + subscription

```bash
gcloud pubsub topics create grafana-logs --project="$PROJECT_ID"
gcloud pubsub subscriptions create grafana-logs-sub \
  --topic=grafana-logs --ack-deadline=60 --project="$PROJECT_ID"
```

### 3. Cloud Logging sink → Pub/Sub

Route only the Cloud Run service logs (keeps volume — and cost — down):

```bash
gcloud logging sinks create grafana-cloud-run-sink \
  "pubsub.googleapis.com/projects/$PROJECT_ID/topics/grafana-logs" \
  --project="$PROJECT_ID" \
  --log-filter='resource.type="cloud_run_revision" AND resource.labels.service_name=("fastapi-app" OR "frontend-app")'

# Grant the sink's auto-created writer identity permission to publish.
SINK_SA=$(gcloud logging sinks describe grafana-cloud-run-sink \
  --project="$PROJECT_ID" --format='value(writerIdentity)')
gcloud pubsub topics add-iam-policy-binding grafana-logs \
  --project="$PROJECT_ID" --member="$SINK_SA" --role=roles/pubsub.publisher
```

### 4. Service account for Alloy to read the subscription

```bash
gcloud iam service-accounts create alloy-log-reader \
  --project="$PROJECT_ID" --display-name="Grafana Alloy log reader"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:alloy-log-reader@$PROJECT_ID.iam.gserviceaccount.com" \
  --role=roles/pubsub.subscriber

# Download the key to the path the compose file mounts.
gcloud iam service-accounts keys create observability/gcp-sa-key.json \
  --iam-account="alloy-log-reader@$PROJECT_ID.iam.gserviceaccount.com"
```

> `observability/gcp-sa-key.json` is git-ignored — never commit it.

### 5. Turn on JSON logs for the backend

```bash
gcloud run services update fastapi-app --region="$REGION" \
  --update-env-vars JSON_LOGS=true
```

(The frontend can stay as-is; its text logs still arrive labelled
`service="frontend-app"`.)

### 6. Configure + start Alloy on the VM

On the GCE VM, add to the `.env` next to `docker-compose.gce.yml`:

```ini
GRAFANA_LOKI_URL=https://logs-prod-012.grafana.net/loki/api/v1/push
GRAFANA_LOKI_USER=123456
GRAFANA_LOKI_TOKEN=glc_xxx...
GCP_PROJECT_ID=your-gcp-project-id
GCP_LOG_SUBSCRIPTION=grafana-logs-sub
```

Then:

```bash
docker compose -f docker-compose.gce.yml up -d alloy
docker logs -f alloy          # should show it connecting to Loki + Pub/Sub
```

### 7. Import the starter dashboard

In Grafana: **Dashboards → New → Import** → upload
`observability/dashboards/overview.json` and pick your Loki data source.

---

## Searching logs (LogQL)

Use **Explore → Loki** in Grafana. Labels available: `service`, `level`,
`component`, `source`, `container`, `env`.

| Need | Query |
|---|---|
| Everything from the backend | `{service="fastapi-app"}` |
| Only errors/warnings | `{service="fastapi-app", level=~"ERROR\|WARNING"}` |
| Odds pipeline only | `{component="odds"}` |
| **Odds API calls** | `{component="odds"} \| json \| event="odds_api_call"` |
| Odds API call rate (per hour) | `sum(count_over_time({component="odds"} \| json \| event="odds_api_call" [1h]))` |
| **Odds API 401s (quota exhausted)** | `{component="odds"} \| json \| oddsapi_status="401"` |
| Scraping issues | `{component="scraper"} \| json \| level=~"ERROR\|WARNING"` |
| Telegram alert decisions | `{component="telegram"}` |
| Auth problems | `{component="auth"} \|~ "(?i)invalid\|unauthor\|fail"` |
| Payments / billing | `{component="payments"}` |
| VM container (e.g. postgres) | `{source="gce_vm", container="postgres"}` |
| Free-text across backend | `{service="fastapi-app"} \|= "national team"` |

---

## Suggested alerts (Grafana → Alerting)

- **Odds API quota** — fire when any `oddsapi_status="401"` appears in 5m.
- **Backend error spike** — `count_over_time({service="fastapi-app", level="ERROR"}[5m]) > 10`.
- **Payment webhook failure** — any `{component="payments", level=~"ERROR\|WARNING"}`.

---

## Known gap

Browser-side (client) frontend errors aren't captured here — this pipeline
covers server logs. Add Sentry or PostHog session-replay later if you need
client-side error/RUM visibility.
