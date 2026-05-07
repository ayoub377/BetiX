"""Billing endpoints — LemonSqueezy hosted checkout, signed webhook, customer portal.

The webhook is the source of truth for ``users.role`` flips: a user clicking
"Get Premium" only triggers the checkout; their tier is granted asynchronously
once LemonSqueezy POSTs the ``subscription_created`` event back to us.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.lemon_squeezy import (
    create_checkout,
    get_subscription,
    verify_webhook_signature,
)
from app.models.database import get_db
from app.models.users import User

logger = logging.getLogger(__name__)
router = APIRouter()


# Subscription statuses that mean "this user should have Premium access".
# Reference: https://docs.lemonsqueezy.com/api/subscriptions
ACTIVE_STATUSES = {"active", "on_trial", "past_due"}
INACTIVE_STATUSES = {"cancelled", "expired", "unpaid", "paused"}


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse LemonSqueezy ISO-8601 timestamps (e.g. ``2025-01-01T00:00:00.000Z``).

    Python 3.11+ ``datetime.fromisoformat`` handles the trailing ``Z`` natively.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception as e:
        logger.warning("Could not parse LS timestamp %r: %s", value, e)
        return None


def _apply_subscription_state(
    user: User,
    *,
    subscription_id: Optional[str],
    customer_id: Optional[str],
    status: Optional[str],
    period_end: Optional[datetime],
) -> None:
    """Mutate ``user`` to reflect the latest LS subscription state.

    Caller is responsible for committing the session.
    """
    if subscription_id:
        user.lemonsqueezy_subscription_id = subscription_id
    if customer_id:
        user.lemonsqueezy_customer_id = customer_id
    if status:
        user.subscription_status = status
    if period_end is not None:
        user.current_period_end = period_end

    # Role transitions. Admins are never auto-demoted by billing — admin is
    # an operational tier independent of payment state.
    if user.role == "admin":
        return
    if status in ACTIVE_STATUSES:
        user.role = "premium"
    elif status in INACTIVE_STATUSES:
        user.role = "normal"
    # Statuses we don't recognise leave the role alone — safer than guessing.


# ─────────────────────────────────────────────────────────────────────────
# /billing/checkout — start a paid subscription flow
# ─────────────────────────────────────────────────────────────────────────
@router.post("/checkout")
async def create_billing_checkout(
    user: User = Depends(get_current_user),
) -> dict:
    """Return a LemonSqueezy hosted-checkout URL for the configured Premium variant.

    The frontend redirects the browser to this URL; LS handles payment and
    POSTs ``subscription_created`` back to ``/billing/webhook``, which is what
    actually flips ``role`` to ``premium``.
    """
    variant_id = os.getenv("LEMONSQUEEZY_PREMIUM_VARIANT_ID")
    if not variant_id:
        raise HTTPException(
            status_code=503,
            detail="Billing is not configured: LEMONSQUEEZY_PREMIUM_VARIANT_ID is unset.",
        )
    if not user.email:
        raise HTTPException(
            status_code=400,
            detail="Your account has no email; cannot create a checkout session.",
        )

    # Optional post-purchase redirect — points the user at our success page,
    # which polls /api/users/me until the webhook flips role=premium.
    redirect_url = os.getenv("LEMONSQUEEZY_CHECKOUT_REDIRECT_URL")

    try:
        url = create_checkout(
            email=user.email,
            variant_id=int(variant_id),
            user_id=str(user.id),
            redirect_url=redirect_url,
        )
    except Exception as e:
        logger.error("LemonSqueezy checkout creation failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Could not create checkout session. Please try again.",
        )

    return {"url": url}


# ─────────────────────────────────────────────────────────────────────────
# /billing/portal — manage existing subscription
# ─────────────────────────────────────────────────────────────────────────
@router.post("/portal")
async def get_billing_portal(
    user: User = Depends(get_current_user),
) -> dict:
    """Return a fresh LS customer-portal URL for self-service management.

    LS rotates these URLs periodically, so we don't persist them — we fetch
    on demand from the subscription's ``urls.customer_portal``.
    """
    if not user.lemonsqueezy_subscription_id:
        raise HTTPException(
            status_code=404,
            detail="No active subscription on file. Subscribe first via /billing/checkout.",
        )
    try:
        sub = get_subscription(user.lemonsqueezy_subscription_id)
    except Exception as e:
        logger.error("LS subscription fetch failed: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="Could not reach billing provider.")

    portal_url = (
        sub.get("data", {}).get("attributes", {}).get("urls", {}).get("customer_portal")
    )
    if not portal_url:
        raise HTTPException(
            status_code=502,
            detail="Billing provider did not return a portal URL.",
        )
    return {"url": portal_url}


# ─────────────────────────────────────────────────────────────────────────
# /billing/webhook — async source of truth for role + subscription state
# ─────────────────────────────────────────────────────────────────────────
@router.post("/webhook")
async def lemonsqueezy_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Handle LemonSqueezy webhook events.

    Security: the request body is HMAC-signed by LS. We must read the **raw**
    bytes (not Pydantic-parse) to verify the signature, then parse JSON.
    """
    secret = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET")
    if not secret:
        # Misconfiguration shouldn't 200-OK the webhook — that would silently
        # accept unsigned payloads if someone forgot to set the env var.
        raise HTTPException(status_code=503, detail="Webhook not configured.")

    body = await request.body()
    signature = request.headers.get("x-signature") or request.headers.get("X-Signature")
    if not verify_webhook_signature(secret, body, signature):
        logger.warning("LS webhook rejected: signature mismatch")
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Webhook body is not valid JSON.")

    meta = payload.get("meta") or {}
    event_name = meta.get("event_name") or ""
    custom_data = meta.get("custom_data") or {}

    data = payload.get("data") or {}
    sub_id = data.get("id")
    sub_attrs = data.get("attributes") or {}
    customer_id = sub_attrs.get("customer_id")
    status = sub_attrs.get("status")
    user_email = sub_attrs.get("user_email")
    renews_at = _parse_iso(sub_attrs.get("renews_at"))
    ends_at = _parse_iso(sub_attrs.get("ends_at"))

    logger.info(
        "LS webhook received: event=%s sub_id=%s customer_id=%s status=%s",
        event_name, sub_id, customer_id, status,
    )

    # Map back to the User row. Resolution order:
    #   1. custom_data.user_id (set by us at checkout — most reliable)
    #   2. existing lemonsqueezy_customer_id on file
    #   3. email lookup (fallback for legacy / hand-created subscriptions)
    user: Optional[User] = None
    custom_user_id = custom_data.get("user_id") if isinstance(custom_data, dict) else None
    if custom_user_id:
        try:
            user = db.query(User).filter(User.id == custom_user_id).one_or_none()
        except Exception:
            user = None
    if user is None and customer_id is not None:
        user = (
            db.query(User)
            .filter(User.lemonsqueezy_customer_id == str(customer_id))
            .one_or_none()
        )
    if user is None and user_email:
        user = db.query(User).filter(User.email == user_email).one_or_none()

    if user is None:
        # 200 OK so LS doesn't keep retrying for a user we don't know about
        # (e.g. a comp/test subscription we didn't initiate).
        logger.warning(
            "LS webhook: no matching user for event=%s custom_user_id=%s customer_id=%s email=%s",
            event_name, custom_user_id, customer_id, user_email,
        )
        return {"status": "no_user"}

    # Pick the best period-end timestamp for this event. ``ends_at`` is set
    # when the subscription is cancelled or expires; ``renews_at`` is the
    # next billing date for active subs.
    period_end = ends_at if event_name in ("subscription_cancelled", "subscription_expired") else renews_at

    _apply_subscription_state(
        user,
        subscription_id=str(sub_id) if sub_id else None,
        customer_id=str(customer_id) if customer_id is not None else None,
        status=status,
        period_end=period_end,
    )
    user.updated_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(
        "LS webhook applied: user=%s role=%s sub_status=%s period_end=%s",
        user.id, user.role, user.subscription_status, user.current_period_end,
    )
    return {"status": "ok"}
