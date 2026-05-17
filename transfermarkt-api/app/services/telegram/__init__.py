"""Telegram alerting subsystem.

Public surface is intentionally small — most callers should only touch:

- :func:`bot_client.send_message` — DM a Telegram chat.
- :func:`link_tokens.create_link_token` / :func:`consume_link_token` —
  one-time tokens used by the bot deep-link flow.
- :func:`alert_dispatcher.maybe_dispatch_alert` — called from inside the
  per-match scrape job after each new snapshot is stored.

Everything else is implementation detail.
"""
