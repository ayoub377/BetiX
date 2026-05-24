"""Tests for the Dixon-Coles per-league CSV list + delete capability.

Drives ``_LocalDataSource`` directly against ``tmp_path`` — the same
exercise GCS would need is covered structurally by the symmetric method
signatures and the shared ``_safe_csv_filename`` guard. Hitting real
GCS would need cloud auth + a live bucket, which is outside the scope
of unit tests.

The route handlers are tested via ``app.dependency_overrides`` so the
admin gate is bypassed without needing a real Firebase token. Each test
isolates its data source via ``DATA_FOLDER_BASE`` monkeypatching +
``reset_data_source()`` so the singleton from a previous test doesn't
leak in.
"""
import datetime
import pytest
from fastapi.testclient import TestClient
from pathlib import Path

import app.services.dixon_coles.dixon_coles_service as dcs
from app.services.dixon_coles.dixon_coles_service import (
    DataNotFoundError,
    _LocalDataSource,
    _safe_csv_filename,
    reset_data_source,
)


CSV_PATTERN = "*.csv"

SAMPLE_CSV = (
    b"Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
    b"01/08/2024,Arsenal,Chelsea,2,1\n"
    b"02/08/2024,Liverpool,Man Utd,1,1\n"
)


# ─────────────────────────────────────────────────────────────────────
# _safe_csv_filename — defence-in-depth path validator
# ─────────────────────────────────────────────────────────────────────

class TestSafeCsvFilename:
    def test_accepts_a_plain_csv_name(self):
        assert _safe_csv_filename("E0.csv") == "E0.csv"
        assert _safe_csv_filename("season_2024_2025.csv") == "season_2024_2025.csv"

    @pytest.mark.parametrize(
        "name",
        [
            "../E0.csv",
            "subdir/E0.csv",
            "subdir\\E0.csv",
            "..\\E0.csv",
            "E0/../other.csv",
        ],
    )
    def test_rejects_path_traversal(self, name):
        # Any input touching a directory separator or '..' must be rejected
        # — the delete path appends the filename straight into a filesystem
        # path and we don't want it walking out of the league folder.
        with pytest.raises(ValueError):
            _safe_csv_filename(name)

    def test_rejects_non_csv_extension(self):
        with pytest.raises(ValueError):
            _safe_csv_filename("model.pkl")

    def test_rejects_dotfile(self):
        with pytest.raises(ValueError):
            _safe_csv_filename(".hidden.csv")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            _safe_csv_filename("")
        with pytest.raises(ValueError):
            _safe_csv_filename("   ")


# ─────────────────────────────────────────────────────────────────────
# _LocalDataSource.list_csvs / delete_csv
# ─────────────────────────────────────────────────────────────────────

class TestLocalDataSourceListAndDelete:
    @pytest.fixture
    def source(self, tmp_path):
        return _LocalDataSource(tmp_path, CSV_PATTERN)

    def test_list_returns_empty_when_league_folder_missing(self, source):
        # No folder yet (a brand-new league the admin is about to upload
        # into for the first time). 200 with [] is the right shape for the
        # UI's empty state.
        assert source.list_csvs("brand_new") == []

    def test_list_returns_sorted_entries_with_metadata(self, source, tmp_path):
        league_dir = tmp_path / "premier_league"
        league_dir.mkdir()
        # Write files out of order on purpose — list_csvs must sort.
        (league_dir / "season_2024.csv").write_bytes(SAMPLE_CSV)
        (league_dir / "season_2023.csv").write_bytes(SAMPLE_CSV * 2)

        rows = source.list_csvs("premier_league")

        assert [r["filename"] for r in rows] == [
            "season_2023.csv",
            "season_2024.csv",
        ]
        # Sizes match what we wrote (no compression / formatting magic).
        assert rows[0]["size_bytes"] == len(SAMPLE_CSV) * 2
        assert rows[1]["size_bytes"] == len(SAMPLE_CSV)
        # last_modified is UTC-aware datetime so the JSON response carries
        # a clear timezone. Non-tz-aware would render ambiguously across
        # local-time prod logs and the UI.
        assert isinstance(rows[0]["last_modified"], datetime.datetime)
        assert rows[0]["last_modified"].tzinfo is not None

    def test_list_ignores_non_csv_files(self, source, tmp_path):
        league_dir = tmp_path / "la_liga"
        league_dir.mkdir()
        (league_dir / "E0.csv").write_bytes(SAMPLE_CSV)
        (league_dir / "README.txt").write_text("notes")
        (league_dir / "model.pkl").write_bytes(b"\x00\x01")

        rows = source.list_csvs("la_liga")
        assert [r["filename"] for r in rows] == ["E0.csv"]

    def test_delete_removes_file_and_returns_path(self, source, tmp_path):
        league_dir = tmp_path / "serie_a"
        league_dir.mkdir()
        target = league_dir / "E0.csv"
        target.write_bytes(SAMPLE_CSV)

        returned = source.delete_csv("serie_a", "E0.csv")

        assert not target.exists()
        # Returned path is the absolute fs path that was removed — handy
        # for audit logs.
        assert "serie_a" in returned and returned.endswith("E0.csv")

    def test_delete_missing_file_raises_data_not_found(self, source, tmp_path):
        (tmp_path / "serie_a").mkdir()
        with pytest.raises(DataNotFoundError):
            source.delete_csv("serie_a", "missing.csv")

    def test_delete_rejects_bad_filename(self, source, tmp_path):
        (tmp_path / "ligue_1").mkdir()
        with pytest.raises(ValueError):
            source.delete_csv("ligue_1", "../escape.csv")

    def test_delete_one_does_not_remove_the_rest(self, source, tmp_path):
        league_dir = tmp_path / "bundesliga"
        league_dir.mkdir()
        (league_dir / "season_2023.csv").write_bytes(SAMPLE_CSV)
        (league_dir / "season_2024.csv").write_bytes(SAMPLE_CSV)

        source.delete_csv("bundesliga", "season_2023.csv")

        remaining = [r["filename"] for r in source.list_csvs("bundesliga")]
        assert remaining == ["season_2024.csv"]


# ─────────────────────────────────────────────────────────────────────
# API routes — drive through FastAPI with the admin gate stubbed out
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    """Build a TestClient that:
      1. Points the data source at a temp directory.
      2. Bypasses the admin Firebase auth so we can hit the endpoints
         without forging a token.

    The data-source singleton is reset both at fixture entry and exit so
    leftover state from another test (the production singleton, a
    different tmp folder) doesn't bleed in.
    """
    # Reset the cached data source so the next _get_data_source() call
    # picks up our monkeypatched DATA_FOLDER_BASE.
    reset_data_source()
    monkeypatch.setattr(dcs, "DATA_FOLDER_BASE", tmp_path)

    from app.core.auth import require_role
    from app.api.api import api_router
    from fastapi import FastAPI

    # Build a minimal app that mounts the same router used in production.
    # FastAPI's TestClient handles the lifecycle so we don't need uvicorn.
    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    # Bypass the admin gate by overriding require_role("admin") — the
    # factory returns a closure, so we override every closure returned
    # for "admin" by patching at the dependency level.
    def _override():
        # Return any non-None object — the route doesn't inspect it.
        return object()

    # require_role builds a fresh dep per call, but FastAPI keys
    # dependency_overrides by the dep callable identity. Easier path:
    # patch the require_role factory itself.
    from fastapi import Depends
    import app.api.endpoints.admin_dixon_coles as admin_module

    # Replace the dependency function used by routes — these are the
    # *callables* FastAPI keyed against when the routes were registered.
    # We inspect every route on the router and override its `dependencies`.
    overrides = {}
    for route in app.routes:
        if not hasattr(route, "dependant"):
            continue
        for dep in route.dependant.dependencies:
            call = dep.call
            if call is None:
                continue
            # require_role's returned closure has name "_dep"; that's
            # the function we need to override.
            if call.__name__ == "_dep":
                overrides[call] = _override

    app.dependency_overrides.update(overrides)

    client = TestClient(app)
    try:
        yield client, tmp_path
    finally:
        reset_data_source()


def _seed(tmp_path: Path, league: str, files: dict[str, bytes]) -> Path:
    league_dir = tmp_path / league
    league_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (league_dir / name).write_bytes(content)
    return league_dir


class TestRoutes:
    def test_get_csvs_returns_listing(self, admin_client):
        client, tmp_path = admin_client
        _seed(tmp_path, "premier_league", {
            "season_2023.csv": SAMPLE_CSV,
            "season_2024.csv": SAMPLE_CSV * 2,
        })

        r = client.get("/api/admin/dixon-coles/leagues/premier_league/csvs")
        assert r.status_code == 200, r.text
        body = r.json()
        assert [row["filename"] for row in body] == [
            "season_2023.csv",
            "season_2024.csv",
        ]
        # Sizes round-trip as ints.
        assert body[0]["size_bytes"] == len(SAMPLE_CSV)
        assert body[1]["size_bytes"] == len(SAMPLE_CSV) * 2

    def test_get_csvs_returns_empty_list_when_no_uploads_yet(self, admin_client):
        client, _ = admin_client
        r = client.get("/api/admin/dixon-coles/leagues/never_used/csvs")
        # 200 + [] (not 404) so the UI's empty-state branch is the same
        # as "league exists but has no files yet."
        assert r.status_code == 200
        assert r.json() == []

    def test_delete_removes_the_file(self, admin_client):
        client, tmp_path = admin_client
        league_dir = _seed(tmp_path, "la_liga", {"E0.csv": SAMPLE_CSV})

        r = client.delete("/api/admin/dixon-coles/leagues/la_liga/csvs/E0.csv")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["league"] == "la_liga"
        assert body["filename"] == "E0.csv"
        assert not (league_dir / "E0.csv").exists()

    def test_delete_missing_file_returns_404(self, admin_client):
        client, tmp_path = admin_client
        _seed(tmp_path, "serie_a", {})  # league folder but no CSVs

        r = client.delete("/api/admin/dixon-coles/leagues/serie_a/csvs/E0.csv")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()

    def test_delete_traversal_attempt_returns_400(self, admin_client):
        client, _ = admin_client
        # FastAPI normalises ../ in path params before routing — to verify
        # the service-layer guard, send a name with a backslash, which the
        # URL parser leaves alone.
        r = client.delete(
            "/api/admin/dixon-coles/leagues/serie_a/csvs/sub%5Cescape.csv"
        )
        assert r.status_code == 400
