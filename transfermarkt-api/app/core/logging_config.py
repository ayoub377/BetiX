"""Centralised logging configuration.

Two modes, picked by the ``JSON_LOGS`` env var:

* ``JSON_LOGS=true`` (production / Cloud Run) — emit one JSON object per log
  record on stdout. Google Cloud Run automatically parses these into
  structured log entries (``severity``, ``message`` + any extra fields), which
  then flow through the Cloud Logging → Pub/Sub → Grafana Alloy → Loki pipeline
  with clean, filterable fields. No regex parsing of text needed downstream.

* unset / ``false`` (local dev) — keep the human-readable single-line format.

Every record also carries a ``component`` field derived from the logger name
(``odds`` / ``scraper`` / ``auth`` / ``payments`` / ``telegram`` / ``api`` /
``core``). Grafana promotes it to a Loki label so you can slice logs by
subsystem ("show me everything from the odds pipeline at WARNING+").

Add ad-hoc structured context to any log call with ``extra=``::

    logger.info("odds api call", extra={"event": "odds_api_call",
                                        "oddsapi_status": 200})

Those keys become top-level fields on the JSON line (and are queryable in Loki).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

# LogRecord attributes that are framework-internal — we never copy these into
# the JSON body (only genuine ``extra={...}`` keys should leak through).
_RESERVED = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "taskName"}

# Logger-name prefix → component label. Longest-prefix wins. Keeps the label
# cardinality low and stable so Loki stays fast.
_COMPONENT_PREFIXES: tuple[tuple[str, str], ...] = (
    ("app.services.odds_api", "odds"),
    ("app.services.odds_tracker", "odds"),
    ("app.services.arbitrage", "odds"),
    ("app.services.flashscore_scraper", "scraper"),
    ("app.services.clubs", "scraper"),
    ("app.services.players", "scraper"),
    ("app.services.competitions", "scraper"),
    ("app.services.dixon_coles", "predictions"),
    ("app.services.telegram", "telegram"),
    ("app.core.lemon_squeezy", "payments"),
    ("app.api.endpoints.billing", "payments"),
    ("app.core.auth", "auth"),
    ("app.api.endpoints", "api"),
    ("app.core", "core"),
)


def component_for(logger_name: str) -> str:
    """Map a logger name to a coarse subsystem label."""
    for prefix, component in _COMPONENT_PREFIXES:
        if logger_name == prefix or logger_name.startswith(prefix + "."):
            return component
    if logger_name.startswith("app."):
        return "app"
    return "other"


class GoogleJsonFormatter(logging.Formatter):
    """Render a LogRecord as a single Cloud Run-friendly JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            # Cloud Run reads "severity" to set the entry's log level.
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "component": component_for(record.name),
            "time": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Merge caller-supplied extra={...} fields.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging() -> None:
    """Install the root logging handler. Call once at process startup."""
    json_logs = os.environ.get("JSON_LOGS", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    level = os.environ.get("LOG_LEVEL", "INFO").upper()

    handler = logging.StreamHandler(sys.stdout)
    if json_logs:
        handler.setFormatter(GoogleJsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    root = logging.getLogger()
    # Replace any handlers a prior basicConfig() / library import installed so
    # we don't double-log.
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
