# auth.py
import logging
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth
from firebase_admin.exceptions import FirebaseError
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.users import User

load_dotenv()
logger = logging.getLogger(__name__)

security = HTTPBearer()


def _admin_email_allowlist() -> set[str]:
    """Comma-separated emails that get auto-promoted to admin on first login."""
    raw = os.environ.get("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def verify_firebase_token(token: str) -> dict:
    """Verify the Firebase JWT and return the decoded payload."""
    try:
        return auth.verify_id_token(token)
    except FirebaseError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid authentication credentials: {e}")


def _get_or_create_user(db: Session, decoded_token: dict) -> User:
    """Look up the User row for this Firebase UID, creating it on first sight.

    Newly-seen UIDs default to role ``normal``, except emails in the
    ``ADMIN_EMAILS`` allowlist which are bootstrapped as admins.
    """
    uid = decoded_token.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

    user = db.query(User).filter(User.firebase_uid == uid).one_or_none()
    if user is not None:
        # Keep email in sync if Firebase has one and ours is empty/stale.
        token_email = decoded_token.get("email")
        if token_email and user.email != token_email:
            user.email = token_email
            db.commit()
        return user

    email = decoded_token.get("email")
    role = "admin" if email and email.lower() in _admin_email_allowlist() else "normal"
    user = User(firebase_uid=uid, email=email, role=role)
    db.add(user)
    try:
        db.commit()
    except Exception:
        db.rollback()
        # Race: another request created the row between SELECT and INSERT.
        user = db.query(User).filter(User.firebase_uid == uid).one_or_none()
        if user is None:
            raise
    db.refresh(user)
    logger.info("Created User row for firebase_uid=%s role=%s", uid, user.role)
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated User row. Raises 401 if the token is invalid."""
    decoded_token = verify_firebase_token(credentials.credentials)
    return _get_or_create_user(db, decoded_token)


def require_role(*allowed_roles: str):
    """Dependency factory that enforces the current user has one of the
    listed roles. Usage: ``Depends(require_role("admin"))``.
    """
    allowed = set(allowed_roles)

    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of roles: {sorted(allowed)}",
            )
        return user

    return _dep


async def has_access(credentials_: HTTPAuthorizationCredentials = Depends(security)):
    """Legacy dependency kept for backward compatibility with existing routes
    that only need to validate a Firebase token without fetching the User row
    (e.g. clubs.py /compare). Returns the decoded token payload.
    """
    return verify_firebase_token(credentials_.credentials)
