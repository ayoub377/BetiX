"""LemonSqueezy API helpers + webhook signature verification.

Single thin layer over the LS REST API used by app/api/endpoints/billing.py.
Keeping this module small and pure (no FastAPI imports) makes it easy to unit
test in isolation against recorded fixtures.
"""

import hashlib
import hmac
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

API_KEY = os.getenv("LEMONSQUEEZY_API_KEY")
STORE_ID = os.getenv("LEMONSQUEEZY_STORE_ID")
BASE_URL = "https://api.lemonsqueezy.com/v1"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/vnd.api+json",
    "Content-Type": "application/vnd.api+json",
}


def _refresh_headers() -> dict:
    """Re-read API_KEY at call time so tests / late-bound env vars work.

    The module-level HEADERS dict is built at import time from the env var,
    which is fine for the prod boot path (env loaded before app starts) but
    fragile for tests that set os.environ after import. This function
    rebuilds the auth header on demand.
    """
    api_key = os.getenv("LEMONSQUEEZY_API_KEY") or API_KEY or ""
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
    }


def list_products() -> list:
    res = requests.get(
        f"{BASE_URL}/products?filter[store_id]={STORE_ID}",
        headers=_refresh_headers(),
        timeout=15,
    )
    res.raise_for_status()
    return res.json()["data"]


def create_checkout(
    email: str,
    variant_id: int,
    user_id: Optional[str] = None,
    redirect_url: Optional[str] = None,
) -> str:
    """Create a hosted-checkout session and return the URL to redirect the user to.

    ``user_id`` (our Postgres ``users.id`` UUID, as a string) is forwarded as
    LemonSqueezy ``custom_data`` so the webhook handler can map subscription
    events back to the User row that initiated the purchase. Without it the
    webhook would have to fall back to email-matching, which is unreliable
    (users can change emails, marketing-list emails differ from auth emails).
    """
    store_id = os.getenv("LEMONSQUEEZY_STORE_ID") or STORE_ID
    checkout_data: dict = {"email": email}
    if user_id:
        # LS spec: arbitrary key/values. We only set user_id; never include PII.
        checkout_data["custom"] = {"user_id": user_id}

    attributes: dict = {
        "checkout_data": checkout_data,
        "custom_price": None,
    }
    if redirect_url:
        # LS post-purchase redirect. If unset, LS uses the store's default.
        attributes["product_options"] = {"redirect_url": redirect_url}

    payload = {
        "data": {
            "type": "checkouts",
            "attributes": attributes,
            "relationships": {
                "store": {"data": {"type": "stores", "id": str(store_id)}},
                "variant": {"data": {"type": "variants", "id": str(variant_id)}},
            },
        }
    }
    res = requests.post(
        f"{BASE_URL}/checkouts",
        headers=_refresh_headers(),
        json=payload,
        timeout=15,
    )
    res.raise_for_status()
    return res.json()["data"]["attributes"]["url"]


def get_subscription(subscription_id: str) -> dict:
    """Fetch full subscription detail. Used by /billing/portal to surface a
    fresh ``urls.customer_portal`` link without persisting it ourselves
    (LS rotates the portal URL periodically)."""
    res = requests.get(
        f"{BASE_URL}/subscriptions/{subscription_id}",
        headers=_refresh_headers(),
        timeout=15,
    )
    res.raise_for_status()
    return res.json()


def verify_webhook_signature(secret: str, body: bytes, signature_header: Optional[str]) -> bool:
    """Constant-time HMAC-SHA256 verification of the LemonSqueezy webhook body.

    LS sends the signature as a hex digest in the ``X-Signature`` header. The
    digest is computed over the **raw** request body (bytes), not the parsed
    JSON — so the calling endpoint must read ``await request.body()`` before
    attempting any Pydantic parsing.
    """
    if not signature_header or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(expected, signature_header.strip())
    except Exception as e:
        logger.warning("LS signature compare failed: %s", e)
        return False
