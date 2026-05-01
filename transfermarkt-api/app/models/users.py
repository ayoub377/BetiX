import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, EmailStr
from sqlalchemy import Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID

from app.models.team import Base


class WaitlistEmail(BaseModel):
    email: EmailStr


class User(Base):
    """Application user. One row per Firebase UID, created lazily on first
    authenticated request. ``role`` and ``subscription_status`` are the source
    of truth for tier-based access control and billing state.
    """

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    firebase_uid = Column(String(128), unique=True, nullable=False, index=True)
    email = Column(String(320), nullable=True, index=True)
    # "normal" | "premium" | "admin" — kept as plain string so role values can be
    # added without an enum migration.
    role = Column(String(32), nullable=False, default="normal")

    # LemonSqueezy billing state (populated by webhook handler in PR3).
    lemonsqueezy_customer_id = Column(String(64), nullable=True)
    lemonsqueezy_subscription_id = Column(String(64), nullable=True)
    subscription_status = Column(String(32), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_users_role", "role"),
    )
