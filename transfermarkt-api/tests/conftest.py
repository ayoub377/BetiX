# Top-level pytest conftest.
#
# Importing User here registers it on the shared SQLAlchemy ``Base`` metadata,
# so the in-memory SQLite fixtures used by tests/odds/* can resolve the
# ``tracked_matches.user_id → users.id`` foreign key added in PR2. Without
# this import, ``Base.metadata.create_all()`` raises ``NoReferencedTableError``.
import app.models.users  # noqa: F401
