#!/usr/bin/env bash
#
# All-in-one Grafana Cloud logging deploy — run in GCP Cloud Shell.
#
# Unlike setup-gcp.sh, this script is fully SELF-CONTAINED: it generates the
# Alloy config + a standalone compose file itself, so you do NOT need the repo
# cloned or any files pre-copied to the VM. Download just this one file and run.
#
# It:
#   1. Creates the Pub/Sub topic + subscription, Cloud Logging sink, and the
#      Alloy service account + key.
#   2. Enables JSON_LOGS on the backend Cloud Run service.
#   3. Writes config.alloy + alloy-compose.yml + .env locally, copies them and
#      the key to the VM, and starts Alloy as a standalone container.
#
# Uses YOUR Cloud Shell identity for the VM copy/SSH (you're project owner), so
# it does NOT depend on the CI service account at all.
#
# USAGE (Cloud Shell):
#   export PROJECT_ID="sharper-bets"
#   export REGION="europe-west9"
#   export GCE_VM_NAME="<vm name>"          # gcloud compute instances list
#   export GCE_VM_ZONE="<vm zone>"
#   export GRAFANA_LOKI_URL="https://logs-prod-XXX.grafana.net/loki/api/v1/push"
#   export GRAFANA_LOKI_USER="123456"
#   export GRAFANA_LOKI_TOKEN="glc_xxx"
#   bash deploy-alloy-standalone.sh
#
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-europe-west9}"
BACKEND_SERVICE="${BACKEND_SERVICE:-fastapi-app}"
TOPIC="grafana-logs"; SUB="grafana-logs-sub"; SINK="grafana-cloud-run-sink"
SA_EMAIL="alloy-log-reader@${PROJECT_ID}.iam.gserviceaccount.com"

: "${GRAFANA_LOKI_URL:?set GRAFANA_LOKI_URL}"
: "${GRAFANA_LOKI_USER:?set GRAFANA_LOKI_USER}"
: "${GRAFANA_LOKI_TOKEN:?set GRAFANA_LOKI_TOKEN}"
: "${GCE_VM_NAME:?set GCE_VM_NAME}"
: "${GCE_VM_ZONE:?set GCE_VM_ZONE}"
: "${PROJECT_ID:?run: gcloud config set project <id>}"

echo "▶ Project=$PROJECT_ID  VM=$GCE_VM_NAME ($GCE_VM_ZONE)"

# ── 1. GCP resources (idempotent) ──────────────────────────────────
echo "▶ 1/4 Pub/Sub + sink + service account"
gcloud pubsub topics create "$TOPIC" 2>/dev/null || echo "  topic exists"
gcloud pubsub subscriptions create "$SUB" --topic "$TOPIC" --ack-deadline 60 2>/dev/null || echo "  sub exists"
gcloud logging sinks create "$SINK" \
  "pubsub.googleapis.com/projects/$PROJECT_ID/topics/$TOPIC" \
  --log-filter='resource.type="cloud_run_revision" AND resource.labels.service_name=("fastapi-app" OR "frontend-app")' \
  2>/dev/null || echo "  sink exists"
SINK_SA=$(gcloud logging sinks describe "$SINK" --format='value(writerIdentity)')
gcloud pubsub topics add-iam-policy-binding "$TOPIC" --member="$SINK_SA" --role=roles/pubsub.publisher -q >/dev/null
gcloud iam service-accounts create alloy-log-reader --display-name "Grafana Alloy log reader" 2>/dev/null || echo "  sa exists"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA_EMAIL" --role=roles/pubsub.subscriber -q >/dev/null
gcloud iam service-accounts keys create /tmp/gcp-sa-key.json --iam-account="$SA_EMAIL" >/dev/null
echo "  ok"

# ── 2. JSON logs on the backend ────────────────────────────────────
echo "▶ 2/4 Enable JSON_LOGS on $BACKEND_SERVICE"
gcloud run services update "$BACKEND_SERVICE" --region "$REGION" --update-env-vars JSON_LOGS=true -q >/dev/null
echo "  ok"

# ── 3. Build the deploy bundle locally ─────────────────────────────
echo "▶ 3/4 Generating config + compose"
mkdir -p ~/alloy-deploy && cd ~/alloy-deploy
cp /tmp/gcp-sa-key.json gcp-sa-key.json
cat > config.alloy <<'ALLOY'
loki.write "grafana_cloud" {
  endpoint {
    url = sys.env("GRAFANA_LOKI_URL")
    basic_auth {
      username = sys.env("GRAFANA_LOKI_USER")
      password = sys.env("GRAFANA_LOKI_TOKEN")
    }
  }
  external_labels = { env = "prod" }
}
loki.source.gcplog "cloud_run" {
  pull {
    project_id             = sys.env("GCP_PROJECT_ID")
    subscription           = sys.env("GCP_LOG_SUBSCRIPTION")
    use_incoming_timestamp = true
    labels = { source = "cloud_run" }
  }
  forward_to = [loki.process.cloud_run.receiver]
}
loki.process "cloud_run" {
  stage.json { expressions = { service = "resource.labels.service_name", severity = "severity", json_payload = "jsonPayload" } }
  stage.json { source = "json_payload" expressions = { component = "component" } }
  stage.template { source = "component" template = "{{ if .Value }}{{ .Value }}{{ else }}app{{ end }}" }
  stage.labels { values = { service = "service", level = "severity", component = "component" } }
  forward_to = [loki.write.grafana_cloud.receiver]
}
discovery.docker "vm" { host = "unix:///var/run/docker.sock" }
loki.source.docker "vm" {
  host       = "unix:///var/run/docker.sock"
  targets    = discovery.docker.vm.targets
  labels     = { source = "gce_vm" }
  forward_to = [loki.write.grafana_cloud.receiver]
}
ALLOY
cat > alloy-compose.yml <<'COMPOSE'
services:
  alloy:
    image: grafana/alloy:latest
    container_name: alloy
    restart: unless-stopped
    command: [run, /etc/alloy/config.alloy, --storage.path=/var/lib/alloy/data]
    volumes:
      - ./config.alloy:/etc/alloy/config.alloy:ro
      - ./gcp-sa-key.json:/etc/alloy/gcp-sa-key.json:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - alloy-data:/var/lib/alloy/data
    environment:
      - GRAFANA_LOKI_URL=${GRAFANA_LOKI_URL}
      - GRAFANA_LOKI_USER=${GRAFANA_LOKI_USER}
      - GRAFANA_LOKI_TOKEN=${GRAFANA_LOKI_TOKEN}
      - GCP_PROJECT_ID=${GCP_PROJECT_ID}
      - GCP_LOG_SUBSCRIPTION=${GCP_LOG_SUBSCRIPTION}
      - GOOGLE_APPLICATION_CREDENTIALS=/etc/alloy/gcp-sa-key.json
volumes:
  alloy-data:
COMPOSE
cat > .env <<ENV
GRAFANA_LOKI_URL=$GRAFANA_LOKI_URL
GRAFANA_LOKI_USER=$GRAFANA_LOKI_USER
GRAFANA_LOKI_TOKEN=$GRAFANA_LOKI_TOKEN
GCP_PROJECT_ID=$PROJECT_ID
GCP_LOG_SUBSCRIPTION=$SUB
ENV
echo "  ok"

# ── 4. Ship to VM and start Alloy ──────────────────────────────────
echo "▶ 4/4 Deploying Alloy to the VM"
gcloud compute ssh "$GCE_VM_NAME" --zone "$GCE_VM_ZONE" --command "mkdir -p ~/alloy-deploy" -q
gcloud compute scp config.alloy alloy-compose.yml gcp-sa-key.json .env \
  "$GCE_VM_NAME:~/alloy-deploy/" --zone "$GCE_VM_ZONE" -q
gcloud compute ssh "$GCE_VM_NAME" --zone "$GCE_VM_ZONE" -q --command \
  "cd ~/alloy-deploy && docker compose -f alloy-compose.yml up -d && sleep 4 && docker logs --tail 30 alloy"

echo
echo "✅ Done. Check Grafana → Explore → Loki:  {service=\"$BACKEND_SERVICE\"}"
