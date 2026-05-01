"""User-facing account endpoints.

Today exposes ``GET /me`` so the frontend can render role-gated UI driven by
the canonical Postgres state rather than Firebase claims or local mocks.
"""

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.quotas import quotas_for
from app.models.users import User

router = APIRouter()


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)) -> dict:
    return {
        "id": str(user.id),
        "firebase_uid": user.firebase_uid,
        "email": user.email,
        "role": user.role,
        "subscription_status": user.subscription_status,
        "current_period_end": (
            user.current_period_end.isoformat() if user.current_period_end else None
        ),
        "quotas": quotas_for(user.role),
    }
