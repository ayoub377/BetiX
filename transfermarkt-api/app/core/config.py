from fastapi import Depends, HTTPException, Request
import redis.asyncio as redis

from app.core.auth import get_current_user
from app.settings import settings
import os

REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
redis_client = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)

# Odds tracking configuration
SCRAPE_INTERVAL_SECONDS = 1200  # how often to poll for new odds (20 minutes)
STOP_BEFORE_KICKOFF_SECONDS = 300  # stop tracking 5 minutes before match start

# Rate limiting configuration from settings
# To modify these values, either:
# 1. Set environment variables: DEFAULT_MAX_REQUESTS=20 DEFAULT_RESET_DURATION=86400
# 2. Modify the values in app/settings.py
# 3. Set RATE_LIMITING_ENABLE=false to completely disable rate limiting
DEFAULT_MAX_REQUESTS = settings.DEFAULT_MAX_REQUESTS
DEFAULT_RESET_DURATION = settings.DEFAULT_RESET_DURATION


async def rate_limit(uid: str, endpoint: str, max_requests: int = None, reset_duration: int = None):
    # Check if rate limiting is enabled
    if not settings.RATE_LIMITING_ENABLE:
        return  # Skip rate limiting if disabled

    # Use environment variables if not specified
    if max_requests is None:
        max_requests = DEFAULT_MAX_REQUESTS
    if reset_duration is None:
        reset_duration = DEFAULT_RESET_DURATION

    redis_key = f"rate_limit:{uid}:{endpoint}"

    # Await the asynchronous Redis `get` call
    request_count = await redis_client.get(redis_key)

    if request_count is None:
        # Initialize the count if it doesn't exist
        await redis_client.set(redis_key, 1, ex=reset_duration)
    else:
        # Convert the request count to an integer
        request_count = int(request_count)
        if request_count >= max_requests:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        # Increment the request count
        await redis_client.incr(redis_key)


async def rate_limit_dependency(
        request: Request,  # Access request details
        uid: str = Depends(get_current_user),
        max_requests: int = None,  # Use environment variable if not specified
):
    endpoint = request.url.path  # Get the current endpoint path
    await rate_limit(uid, endpoint, max_requests)
