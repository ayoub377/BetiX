#!/usr/bin/env bash
#
# One-shot Grafana Cloud logging setup — run in GCP Cloud Shell.
#
# Cloud Shell is already authenticated with gcloud, so this avoids all the
# local SSH/plink pain. It creates the Pub/Sub topic + subscription, the
# Cloud Logging sink, the Alloy service account + key, turns on JSON logs for
# the backend, then pushes the key + a .env to the GCE VM and starts Alloy.
#
# ──────────────────────────────────────────────────────────────────
# PREREQUISITES
#   1. PR #40 is merged AND the scraper deploy has run, so ~/observability and
#      ~/docker-compose.gce.yml exist on the VM. (Or scp them yourself first.)
#   2. You have your 3 Grafana Cloud Loki values (see observability/README.md §1).
#
# USAGE (in Cloud Shell):
#   export GRAFANA_LOKI_URL="https://logs-prod-XXX.grafana.net/loki/api/v1/push"
#   export GRAFANA_LOKI_USER="123456"
#   export GRAFANA_LOKI_TOKEN="glc_xxx"
#   export GCE_VM_NAME="your-vm-name"
#   export GCE_VM_ZONE="europe-west9-a"
#   # optional: export PROJECT_ID=... REGION=... BACKEND_SERVICE=...
#   bash observability/setup-gcp.sh
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-europe-west9}"
BACKEND_SERVICE="${BACKEND_SERVICE:-fastapi-app}"
TOPIC="grafana-logs"
SUBSCRIPTION="grafana-logs-sub"
SINK="grafana-cloud-run-sink"
SA_NAME="alloy-log-reader"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
# Cloud Run services whose logs we route. Edit if you rename services.
SERVICE_FILTER='resource.type="cloud_run_revision" AND resource.labels.service_name=("fastapi-app" OR "frontend-app")'

# ── Validate required inputs ───────────────────────────────────────
: "${GRAFANA_LOKI_URL:?set GRAFANA_LOKI_URL}"
: "${GRAFANA_LOKI_USER:?set GRAFANA_LOKI_USER}"
: "${GRAFANA_LOKI_TOKEN:?set GRAFANA_LOKI_TOKEN}"
: "${GCE_VM_NAME:?set GCE_VM_NAME}"
: "${GCE_VM_ZONE:?set GCE_VM_ZONE}"
: "${PROJECT_ID:?could not resolve PROJECT_ID — run: gcloud config set project <id>}"

echo "▶ Project=$PROJECT_ID  Region=$REGION  VM=$GCE_VM_NAME ($GCE_VM_ZONE)"
echo

# ── 1. Pub/Sub topic + subscription (idempotent) ───────────────────
echo "▶ 1/5 Pub/Sub topic + subscription"
gcloud pubsub topics create "$TOPIC" --project "$PROJECT_ID" 2>/dev/null \
  && echo "  created topic $TOPIC" || echo "  topic $TOPIC already exists"
gcloud pubsub subscriptions create "$SUBSCRIPTION" --topic "$TOPIC" \
  --ack-deadline 60 --project "$PROJECT_ID" 2>/dev/null \
  && echo "  created subscription $SUBSCRIPTION" || echo "  subscription $SUBSCRIPTION already exists"

# ── 2. Cloud Logging sink → Pub/Sub ────────────────────────────────
echo "▶ 2/5 Cloud Logging sink"
gcloud logging sinks create "$SINK" \
  "pubsub.googleapis.com/projects/$PROJECT_ID/topics/$TOPIC" \
  --project "$PROJECT_ID" --log-filter="$SERVICE_FILTER" 2>/dev/null \
  && echo "  created sink $SINK" || echo "  sink $SINK already exists"
SINK_SA=$(gcloud logging sinks describe "$SINK" --project "$PROJECT_ID" --format='value(writerIdentity)')
gcloud pubsub topics add-iam-policy-binding "$TOPIC" --project "$PROJECT_ID" \
  --member="$SINK_SA" --role=roles/pubsub.publisher >/dev/null
echo "  granted publish to sink identity"

# ── 3. Alloy service account + key ─────────────────────────────────
echo "▶ 3/5 Alloy service account + key"
gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT_ID" \
  --display-name "Grafana Alloy log reader" 2>/dev/null \
  && echo "  created $SA_EMAIL" || echo "  $SA_EMAIL already exists"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/pubsub.subscriber >/dev/null
KEY_TMP="$(mktemp)"
gcloud iam service-accounts keys create "$KEY_TMP" --iam-account="$SA_EMAIL" >/dev/null
echo "  minted key"

# ── 4. Turn on JSON logs for the backend ───────────────────────────
echo "▶ 4/5 Enable JSON_LOGS on $BACKEND_SERVICE"
gcloud run services update "$BACKEND_SERVICE" --region "$REGION" \
  --project "$PROJECT_ID" --update-env-vars JSON_LOGS=true >/dev/null
echo "  done"

# ── 5. Push key + .env to the VM and start Alloy ───────────────────
echo "▶ 5/5 Configure VM and start Alloy"
gcloud compute ssh "$GCE_VM_NAME" --zone "$GCE_VM_ZONE" --project "$PROJECT_ID" \
  --command "mkdir -p ~/observability" --quiet
gcloud compute scp "$KEY_TMP" \
  "$GCE_VM_NAME:~/observability/gcp-sa-key.json" \
  --zone "$GCE_VM_ZONE" --project "$PROJECT_ID" --quiet
rm -f "$KEY_TMP"

gcloud compute ssh "$GCE_VM_NAME" --zone "$GCE_VM_ZONE" --project "$PROJECT_ID" --quiet --command "
  cat > ~/.env <<ENV
GRAFANA_LOKI_URL=$GRAFANA_LOKI_URL
GRAFANA_LOKI_USER=$GRAFANA_LOKI_USER
GRAFANA_LOKI_TOKEN=$GRAFANA_LOKI_TOKEN
GCP_PROJECT_ID=$PROJECT_ID
GCP_LOG_SUBSCRIPTION=$SUBSCRIPTION
ENV
  chmod 600 ~/.env ~/observability/gcp-sa-key.json
  docker compose -f ~/docker-compose.gce.yml up -d alloy
  sleep 3
  docker logs --tail 25 alloy
"

echo
echo "✅ Done. Alloy is running on the VM. Check Grafana → Explore → Loki:"
echo "     {service=\"$BACKEND_SERVICE\"}"
