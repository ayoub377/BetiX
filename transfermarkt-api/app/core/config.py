from typing import Mapping

from fastapi import Depends, HTTPException, Request
import redis.asyncio as redis

from app.core.auth import get_current_user
from app.core.quotas import normalize_role
from app.models.users import User
from app.settings import settings
import os

REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
redis_client = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)

# Odds tracking configuration
SCRAPE_INTERVAL_SECONDS = 1200  # legacy fallback; per-tier intervals live in app/core/quotas.py
STOP_BEFORE_KICKOFF_SECONDS = 300  # stop tracking 5 minutes before match start

# The Odds API sharp-overlay cadence.
#
# The sharp (Pinnacle/Betfair) overlay is *supplementary* to the
# FlashScore-scraped primary line, so it does not need refreshing on every
# tick. Fetching it once every N scrape cycles cuts the overlay's Odds API
# spend ~N×. The primary line (FlashScore) and any explicitly-tracked market
# (e.g. Over/Under) are unaffected and still refresh every cycle.
#
#   N = 1  → every cycle (legacy behaviour, most expensive)
#   N = 3  → at a 20-min cadence, ~one sharp refresh per hour (default)
#
# Cost matters: The Odds API bills (markets × regions) per odds call, so each
# avoided sharp call saves `len(ODDS_API_REGIONS)` credits. See SPECS.md §6.
SHARP_ODDS_EVERY_N_CYCLES = max(1, int(os.environ.get("SHARP_ODDS_EVERY_N_CYCLES", "3")))

# Rate limiting configuration from settings
# To modify these values, either:
# 1. Set environment variables: DEFAULT_MAX_REQUESTS=20 DEFAULT_RESET_DURATION=86400
# 2. Modify the values in app/settings.py
# 3. Set RATE_LIMITING_ENABLE=false to completely disable rate limiting
DEFAULT_MAX_REQUESTS = settings.DEFAULT_MAX_REQUESTS
DEFAULT_RESET_DURATION = settings.DEFAULT_RESET_DURATION


async def rate_limit(uid: str, endpoint: str, max_requests: int = None, reset_duration: int = None):
    """Legacy single-quota rate limiter. New code should prefer
    :func:`tier_aware_rate_limit` which honours the per-role matrix."""
    if not settings.RATE_LIMITING_ENABLE:
        return

    if max_requests is None:
        max_requests = DEFAULT_MAX_REQUESTS
    if reset_duration is None:
        reset_duration = DEFAULT_RESET_DURATION

    redis_key = f"rate_limit:{uid}:{endpoint}"
    request_count = await redis_client.get(redis_key)

    if request_count is None:
        await redis_client.set(redis_key, 1, ex=reset_duration)
    else:
        request_count = int(request_count)
        if request_count >= max_requests:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        await redis_client.incr(redis_key)


async def tier_aware_rate_limit(
    user: User,
    endpoint: str,
    tier_quotas: Mapping[str, int],
    reset_duration: int = DEFAULT_RESET_DURATION,
) -> None:
    """Per-user, per-endpoint quota enforcement that respects role tiers.

    ``tier_quotas`` is the per-role limit dict from :mod:`app.core.quotas`
    (e.g. ``DAILY_COMPARE_LIMIT``). ``-1`` means unlimited; admin tiers
    typically use that value to skip the check entirely.

    Always runs (independent of ``RATE_LIMITING_ENABLE``) — these aren't
    soft anti-abuse caps, they're product tier boundaries.
    """
    role = normalize_role(user.role)
    max_requests = tier_quotas.get(role, tier_quotas.get("normal", 0))
    if max_requests is None or max_requests < 0:
        return  # unlimited

    redis_key = f"rate_limit:{user.firebase_uid}:{endpoint}"
    current = await redis_client.get(redis_key)

    if current is None:
        await redis_client.set(redis_key, 1, ex=reset_duration)
        return

    current_int = int(current)
    if current_int >= max_requests:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily limit reached for your tier ({role}: {max_requests}/day). "
                "Upgrade for more requests."
            ),
        )
    await redis_client.incr(redis_key)


def make_tier_rate_limit_dependency(tier_quotas: Mapping[str, int]):
    """Build a FastAPI dependency that enforces ``tier_quotas`` on the
    calling endpoint. Each call site passes in the relevant quota dict
    from :mod:`app.core.quotas`, e.g.::

        from app.core.quotas import DAILY_COMPARE_LIMIT
        from app.core.config import make_tier_rate_limit_dependency

        compare_quota = make_tier_rate_limit_dependency(DAILY_COMPARE_LIMIT)

        @router.get("/compare/...", dependencies=[Depends(compare_quota)])
        ...
    """

    async def _dep(
        request: Request,
        user: User = Depends(get_current_user),
    ) -> None:
        await tier_aware_rate_limit(user, request.url.path, tier_quotas)

    return _dep


async def rate_limit_dependency(
        request: Request,  # Access request details
        user: User = Depends(get_current_user),
        max_requests: int = None,  # Use environment variable if not specified
):
    endpoint = request.url.path  # Get the current endpoint path
    await rate_limit(user.firebase_uid, endpoint, max_requests)
