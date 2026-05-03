"""Tier-aware quota constants. Single source of truth for the access matrix
returned by /api/users/me and enforced by the rate-limit dependency, the
/odds/track endpoint, and the per-tier polling scheduler.

Use ``-1`` for unlimited.
"""

# Per-day call limits keyed by role.
DAILY_PREDICT_LIMIT = {"normal": 5, "premium": 100, "admin": -1}
DAILY_COMPARE_LIMIT = {"normal": 5, "premium": 100, "admin": -1}
# Per-day NEW track creations (POST /odds/track). Untracking + re-tracking
# the same match the same day still counts each time.
DAILY_TRACK_LIMIT = {"normal": 1, "premium": 10, "admin": -1}

# How many trackers a user can have running simultaneously. Untracking a
# match frees a slot.
CONCURRENT_TRACKER_LIMIT = {"normal": 1, "premium": 10, "admin": -1}

# How often the scheduler refreshes odds for a tracked match.
TRACK_POLL_INTERVAL_SECONDS = {
    "normal": 45 * 60,   # 45 minutes
    "premium": 10 * 60,  # 10 minutes
    "admin": 10 * 60,
}

# How far in the future a match's kickoff can be when starting tracking.
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
        "daily_track_limit": DAILY_TRACK_LIMIT[role],
        "concurrent_tracker_limit": CONCURRENT_TRACKER_LIMIT[role],
        "track_poll_interval_seconds": TRACK_POLL_INTERVAL_SECONDS[role],
        "track_kickoff_lookahead_seconds": TRACK_KICKOFF_LOOKAHEAD_SECONDS[role],
    }


def normalize_role(role: str) -> str:
    return role if role in DAILY_PREDICT_LIMIT else "normal"
