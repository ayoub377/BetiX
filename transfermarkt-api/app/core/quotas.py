"""Tier-aware quota constants. Single source of truth for the access matrix
returned by /api/users/me and (in PR2) enforced in the rate-limit dependency
and tracking endpoint.

Use ``-1`` for unlimited.
"""

# Per-day call limits keyed by role.
DAILY_PREDICT_LIMIT = {"normal": 5, "premium": 100, "admin": -1}
DAILY_COMPARE_LIMIT = {"normal": 5, "premium": 100, "admin": -1}

# Tracking caps & polling cadence (consumed in PR2).
CONCURRENT_TRACKER_LIMIT = {"normal": 3, "premium": 50, "admin": -1}
TRACK_POLL_INTERVAL_SECONDS = {"normal": 3600, "premium": 600, "admin": 600}
TRACK_KICKOFF_LOOKAHEAD_SECONDS = {
    "normal": 12 * 3600,
    "premium": 48 * 3600,
    "admin": -1,
}


def quotas_for(role: str) -> dict:
    """Return the full quota dict for a given role. Falls back to ``normal``
    if the role is unrecognised so a misconfigured row never blows up the API.
    """
    role = role if role in DAILY_PREDICT_LIMIT else "normal"
    return {
        "role": role,
        "daily_predict_limit": DAILY_PREDICT_LIMIT[role],
        "daily_compare_limit": DAILY_COMPARE_LIMIT[role],
        "concurrent_tracker_limit": CONCURRENT_TRACKER_LIMIT[role],
        "track_poll_interval_seconds": TRACK_POLL_INTERVAL_SECONDS[role],
        "track_kickoff_lookahead_seconds": TRACK_KICKOFF_LOOKAHEAD_SECONDS[role],
    }
