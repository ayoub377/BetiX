"""Admin-only endpoints for managing Dixon-Coles training data and models.

All routes require role=admin. The data is read/written via the data-source
abstraction in dixon_coles_service, so the same routes work whether
DIXON_COLES_DATA_BUCKET is set (GCS-backed in production) or not (local
folder in dev).
"""

import datetime
import io
import logging
import re
from pathlib import Path
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.auth import require_role
from app.models.users import User
from app.services.dixon_coles.dixon_coles_service import (
    REQUIRED_COLS,
    DataNotFoundError,
    _get_data_source,
    _get_model_store,
    train_model_for_league,
)

router = APIRouter()

# 20 MB is far more than a typical season CSV (~30 KB), but leaves headroom
# for combined multi-season files an admin might prefer to upload in one go.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
LEAGUE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")


def _validate_league_slug(league: str) -> str:
    """Normalise + validate a league identifier so it can safely become a path/blob segment."""
    slug = league.strip().lower().replace(" ", "_")
    if not LEAGUE_SLUG_RE.match(slug):
        raise HTTPException(
            status_code=400,
            detail="Invalid league identifier. Use lowercase letters, digits and underscores (max 64 chars).",
        )
    return slug


class LeagueOverview(BaseModel):
    league: str
    csv_count: int
    last_uploaded: Optional[datetime.datetime]
    model_trained: bool
    model_last_trained: Optional[datetime.datetime]


class UploadResponse(BaseModel):
    league: str
    filename: str
    rows: int
    stored_at: str


class CsvFileInfo(BaseModel):
    """One row in the admin's per-league CSV listing."""
    filename: str
    size_bytes: int
    last_modified: Optional[datetime.datetime]


class DeleteCsvResponse(BaseModel):
    league: str
    filename: str
    deleted_from: str


class TrainAdminResponse(BaseModel):
    status: str
    message: str
    model_path: Optional[str] = None


@router.get("/leagues", response_model=List[LeagueOverview])
def list_admin_leagues(_admin: User = Depends(require_role("admin"))):
    """List every league the data source knows about, with upload/training status."""
    ds = _get_data_source()
    ms = _get_model_store()
    out: List[LeagueOverview] = []
    for league in ds.list_leagues():
        last_trained = ms.model_last_modified(league)
        out.append(
            LeagueOverview(
                league=league,
                csv_count=ds.csv_count(league),
                last_uploaded=ds.last_uploaded(league),
                model_trained=last_trained is not None,
                model_last_trained=last_trained,
            )
        )
    return out


@router.post("/leagues/{league}/upload", response_model=UploadResponse)
async def upload_league_csv(
    league: str,
    file: UploadFile = File(...),
    _admin: User = Depends(require_role("admin")),
):
    """Upload a CSV file into the league's data folder.

    The CSV must contain the standard football-data.co.uk columns required
    by the Dixon-Coles trainer (Date, HomeTeam, AwayTeam, FTHG, FTAG).
    Files are validated before being persisted so a bad upload can't poison
    training.
    """
    slug = _validate_league_slug(league)

    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted.")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024} MB).",
        )

    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"CSV is missing required columns: {missing}. "
                f"Required columns: {REQUIRED_COLS}"
            ),
        )

    ds = _get_data_source()
    try:
        stored_at = ds.upload_csv(slug, filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.exception("Failed to upload CSV for league %s", slug)
        raise HTTPException(status_code=500, detail=f"Storage error: {e}")

    return UploadResponse(
        league=slug,
        filename=Path(filename).name,
        rows=len(df),
        stored_at=stored_at,
    )


@router.get("/leagues/{league}/csvs", response_model=List[CsvFileInfo])
def list_league_csvs(
    league: str,
    _admin: User = Depends(require_role("admin")),
):
    """List every CSV currently stored for a league, with size + mtime.

    Powers the "manage uploads" panel in the admin UI — the admin needs
    to see which weekly file is already there before deciding whether to
    delete + re-upload an updated copy. Returns an empty list (200) when
    the league folder hasn't been created yet, rather than a 404, so the
    UI can render the "no files yet" state generically.
    """
    slug = _validate_league_slug(league)
    ds = _get_data_source()
    try:
        rows = ds.list_csvs(slug)
    except Exception as e:
        logging.exception("Failed to list CSVs for league %s", slug)
        raise HTTPException(status_code=500, detail=f"Storage error: {e}")
    return [CsvFileInfo(**r) for r in rows]


@router.delete(
    "/leagues/{league}/csvs/{filename}",
    response_model=DeleteCsvResponse,
)
def delete_league_csv(
    league: str,
    filename: str,
    _admin: User = Depends(require_role("admin")),
):
    """Delete a single CSV from a league folder.

    Intended workflow: each weekly football-data.co.uk drop has the same
    filename (e.g. ``E0.csv``) but the row count grows. Uploading a new
    file with the same name **overwrites** in place, so duplicates only
    happen when the *filename* differs from the prior upload (a renamed
    weekly file, an old season-snapshot left over from the prior cycle,
    etc.). This endpoint is the cleanup lever for that case.

    The trained model is left alone — call ``POST /leagues/{league}/train``
    afterwards to regenerate it with the cleaned data.
    """
    slug = _validate_league_slug(league)
    ds = _get_data_source()
    try:
        deleted_from = ds.delete_csv(slug, filename)
    except DataNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        # _safe_csv_filename rejects bad input — surface as 400.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.exception(
            "Failed to delete CSV '%s' for league %s", filename, slug,
        )
        raise HTTPException(status_code=500, detail=f"Storage error: {e}")
    return DeleteCsvResponse(
        league=slug,
        filename=filename,
        deleted_from=deleted_from,
    )


@router.post("/leagues/{league}/train", response_model=TrainAdminResponse)
def train_league(
    league: str,
    force_refit: bool = True,
    _admin: User = Depends(require_role("admin")),
):
    """Train (or retrain) the Dixon-Coles model for a league.

    Defaults to force_refit=True because the typical admin flow is
    "I just uploaded new CSVs, retrain now". Pass ?force_refit=false to
    short-circuit when a model already exists.

    NB: training is currently synchronous. For very large leagues this can
    take a minute or two — long enough to hit Cloud Run request timeouts.
    Move to a background task / job queue when that becomes a problem.
    """
    slug = _validate_league_slug(league)
    try:
        result = train_model_for_league(slug, force_refit=force_refit)
        return TrainAdminResponse(**result)
    except DataNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=f"Training failed: {e}")
