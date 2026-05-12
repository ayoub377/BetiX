import io
import os
import pickle
import pandas as pd
import numpy as np
import math
import logging
from scipy.special import loggamma
from scipy.optimize import minimize
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional, Iterable
import datetime
import re
from scipy.stats import poisson

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# !!! IMPORTANT: Update these paths to match your new structure !!!
DATA_FOLDER_BASE = Path("./app/data/leagues")
MODEL_DIR = Path("./trained_models")
# !!! -------------------------------------------------------- !!!

CSV_PATTERN = "*.csv"
REQUIRED_COLS = ['Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG']
FIXED_XI = 0.0076
MAX_GOALS_PREDICT = 7
MODEL_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_MODEL_FILENAME_TEMPLATE = 'dixon_coles_{league}_model.pkl'

# --- Data source / model store configuration ---
# When DIXON_COLES_DATA_BUCKET is set (production on Cloud Run), CSVs are read
# from gs://<bucket>/<DIXON_COLES_DATA_PREFIX>/<league>/*.csv and trained model
# pickles are written to gs://<bucket>/<DIXON_COLES_MODEL_PREFIX>/<league>.pkl.
# One bucket, two prefixes — keeps IAM grants simple.
# In local dev (no env var) both fall back to the project's filesystem.
DATA_BUCKET_ENV = "DIXON_COLES_DATA_BUCKET"
DATA_PREFIX_ENV = "DIXON_COLES_DATA_PREFIX"
MODEL_PREFIX_ENV = "DIXON_COLES_MODEL_PREFIX"
DEFAULT_DATA_PREFIX = "leagues"
DEFAULT_MODEL_PREFIX = "models"

# --- In-Memory Model Cache ---
# This dictionary will store loaded models to avoid disk I/O on every prediction
_model_cache: Dict[str, Tuple[Dict, Dict, int]] = {}


# --- Helper Function for Model File Path ---
def get_model_file_path(league_name: str, template: str = DEFAULT_MODEL_FILENAME_TEMPLATE) -> Path:
    """Constructs the model file path for a given league."""
    sanitized_league_name = league_name.lower().replace(" ", "_").replace("/", "_")
    filename = template.format(league=sanitized_league_name)
    return MODEL_DIR / filename


# --- Custom Exceptions for API Error Handling ---
class ModelNotFoundError(Exception):
    pass


class TeamNotFoundError(Exception):
    pass


class DataNotFoundError(Exception):
    pass


# --- 1. Data Loading and Combination (League Specific) ---


class _LocalDataSource:
    """Reads/writes league CSVs on the local filesystem."""

    def __init__(self, base: Path, pattern: str):
        self._base = base
        self._pattern = pattern

    def location(self, league_name: str) -> str:
        return str(self._base / league_name)

    def iter_csvs(self, league_name: str) -> Iterable[Tuple[str, bytes]]:
        folder = self._base / league_name
        if not folder.is_dir():
            raise DataNotFoundError(
                f"Data folder for league '{league_name}' not found at {folder}"
            )
        files = sorted(folder.glob(self._pattern))
        if not files:
            raise DataNotFoundError(
                f"No CSV files found matching '{self._pattern}' in {folder}"
            )
        for f in files:
            yield f.name, f.read_bytes()

    def list_leagues(self) -> List[str]:
        if not self._base.is_dir():
            return []
        return sorted(p.name for p in self._base.iterdir() if p.is_dir())

    def csv_count(self, league_name: str) -> int:
        folder = self._base / league_name
        return sum(1 for _ in folder.glob(self._pattern)) if folder.is_dir() else 0

    def last_uploaded(self, league_name: str) -> Optional[datetime.datetime]:
        folder = self._base / league_name
        if not folder.is_dir():
            return None
        files = list(folder.glob(self._pattern))
        if not files:
            return None
        return datetime.datetime.fromtimestamp(
            max(f.stat().st_mtime for f in files), tz=datetime.timezone.utc
        )

    def upload_csv(self, league_name: str, filename: str, content: bytes) -> str:
        folder = self._base / league_name
        folder.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name
        if not safe_name.lower().endswith(".csv"):
            raise ValueError("Only .csv files are allowed.")
        target = folder / safe_name
        target.write_bytes(content)
        return str(target)


class _GCSDataSource:
    """Reads/writes league CSVs in gs://<bucket>/<prefix>/<league>/*.csv."""

    def __init__(self, bucket: str, prefix: str = DEFAULT_DATA_PREFIX):
        # Lazy import: keeps google-cloud-storage optional for local dev installs.
        from google.cloud import storage

        self._bucket_name = bucket
        self._prefix = prefix.strip("/")
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket)

    def location(self, league_name: str) -> str:
        return f"gs://{self._bucket_name}/{self._prefix}/{league_name}/"

    def iter_csvs(self, league_name: str) -> Iterable[Tuple[str, bytes]]:
        prefix = f"{self._prefix}/{league_name}/"
        blobs = [
            b for b in self._client.list_blobs(self._bucket, prefix=prefix)
            if b.name.lower().endswith(".csv")
        ]
        if not blobs:
            raise DataNotFoundError(
                f"No CSV files found at gs://{self._bucket_name}/{prefix}"
            )
        for blob in blobs:
            yield blob.name.rsplit("/", 1)[-1], blob.download_as_bytes()

    def list_leagues(self) -> List[str]:
        prefix = f"{self._prefix}/"
        leagues: set[str] = set()
        for blob in self._client.list_blobs(self._bucket, prefix=prefix):
            rest = blob.name[len(prefix):]
            if "/" in rest:
                leagues.add(rest.split("/", 1)[0])
        return sorted(leagues)

    def csv_count(self, league_name: str) -> int:
        prefix = f"{self._prefix}/{league_name}/"
        return sum(
            1 for b in self._client.list_blobs(self._bucket, prefix=prefix)
            if b.name.lower().endswith(".csv")
        )

    def last_uploaded(self, league_name: str) -> Optional[datetime.datetime]:
        prefix = f"{self._prefix}/{league_name}/"
        times = [
            b.updated for b in self._client.list_blobs(self._bucket, prefix=prefix)
            if b.name.lower().endswith(".csv") and b.updated is not None
        ]
        return max(times) if times else None

    def upload_csv(self, league_name: str, filename: str, content: bytes) -> str:
        safe_name = Path(filename).name
        if not safe_name.lower().endswith(".csv"):
            raise ValueError("Only .csv files are allowed.")
        blob_name = f"{self._prefix}/{league_name}/{safe_name}"
        blob = self._bucket.blob(blob_name)
        blob.upload_from_string(content, content_type="text/csv")
        return f"gs://{self._bucket_name}/{blob_name}"


_data_source_singleton: Optional[Any] = None


def _get_data_source():
    """Return the configured data source — GCS when the bucket env var is set, else local."""
    global _data_source_singleton
    if _data_source_singleton is not None:
        return _data_source_singleton

    bucket = (os.environ.get(DATA_BUCKET_ENV) or "").strip()
    if bucket:
        prefix = os.environ.get(DATA_PREFIX_ENV, DEFAULT_DATA_PREFIX)
        logging.info(f"Dixon-Coles data source: GCS bucket '{bucket}' prefix '{prefix}'")
        _data_source_singleton = _GCSDataSource(bucket, prefix)
    else:
        logging.info(f"Dixon-Coles data source: local folder '{DATA_FOLDER_BASE}'")
        _data_source_singleton = _LocalDataSource(DATA_FOLDER_BASE, CSV_PATTERN)
    return _data_source_singleton


def reset_data_source() -> None:
    """Clear the cached data source. Useful in tests after mutating env vars."""
    global _data_source_singleton
    _data_source_singleton = None


# --- Model storage abstraction ---------------------------------------------
#
# Mirrors the data source split: pickles live either on local disk
# (dev) or in GCS (prod). The store is selected by the same env var that
# picks the data source, so a single bucket holds both. Methods accept any
# casing/spacing of the league name and slugify internally.


def _league_slug(league_name: str) -> str:
    """Canonical form for model filenames/blob keys ('Serie A' → 'serie_a')."""
    return league_name.lower().replace(" ", "_").replace("/", "_")


class _LocalModelStore:
    """Persists model pickles under MODEL_DIR on the local filesystem."""

    def __init__(self, base: Path, template: str):
        self._base = base
        self._template = template
        self._base.mkdir(parents=True, exist_ok=True)

    def _path(self, league_name: str) -> Path:
        return self._base / self._template.format(league=_league_slug(league_name))

    def location(self, league_name: str) -> str:
        return str(self._path(league_name))

    def save_model(self, league_name: str, payload: bytes) -> str:
        path = self._path(league_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return str(path)

    def load_model(self, league_name: str) -> bytes:
        path = self._path(league_name)
        if not path.exists():
            raise ModelNotFoundError(
                f"No pre-trained model found for league '{league_name}'. Please train it first."
            )
        return path.read_bytes()

    def model_exists(self, league_name: str) -> bool:
        return self._path(league_name).exists()

    def model_last_modified(self, league_name: str) -> Optional[datetime.datetime]:
        path = self._path(league_name)
        if not path.exists():
            return None
        return datetime.datetime.fromtimestamp(path.stat().st_mtime, tz=datetime.timezone.utc)

    def list_models(self) -> List[str]:
        leagues: List[str] = []
        for f in self._base.glob("*.pkl"):
            match = re.search(r'dixon_coles_(.*?)_model\.pkl', f.name)
            if match:
                leagues.append(match.group(1).replace("_", " "))
        return sorted(leagues)


class _GCSModelStore:
    """Persists model pickles under gs://<bucket>/<prefix>/<league>.pkl."""

    def __init__(self, bucket: str, prefix: str, template: str):
        from google.cloud import storage  # lazy

        self._bucket_name = bucket
        self._prefix = prefix.strip("/")
        self._template = template
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket)

    def _blob_name(self, league_name: str) -> str:
        return f"{self._prefix}/{self._template.format(league=_league_slug(league_name))}"

    def location(self, league_name: str) -> str:
        return f"gs://{self._bucket_name}/{self._blob_name(league_name)}"

    def save_model(self, league_name: str, payload: bytes) -> str:
        blob = self._bucket.blob(self._blob_name(league_name))
        blob.upload_from_string(payload, content_type="application/octet-stream")
        return self.location(league_name)

    def load_model(self, league_name: str) -> bytes:
        blob = self._bucket.blob(self._blob_name(league_name))
        try:
            return blob.download_as_bytes()
        except Exception as e:
            # Both NotFound and Forbidden funnel through the same user-facing
            # error: from the predict endpoint's perspective, the model just
            # isn't available.
            raise ModelNotFoundError(
                f"No pre-trained model found for league '{league_name}' at {self.location(league_name)}: {e}"
            )

    def model_exists(self, league_name: str) -> bool:
        return self._bucket.blob(self._blob_name(league_name)).exists()

    def model_last_modified(self, league_name: str) -> Optional[datetime.datetime]:
        # get_blob does a metadata GET; returns None on 404 instead of raising.
        blob = self._bucket.get_blob(self._blob_name(league_name))
        return blob.updated if blob is not None else None

    def list_models(self) -> List[str]:
        prefix = f"{self._prefix}/"
        leagues: List[str] = []
        for blob in self._client.list_blobs(self._bucket, prefix=prefix):
            name = blob.name[len(prefix):]
            match = re.search(r'dixon_coles_(.*?)_model\.pkl', name)
            if match:
                leagues.append(match.group(1).replace("_", " "))
        return sorted(leagues)


_model_store_singleton: Optional[Any] = None


def _get_model_store():
    """Return the configured model store (GCS when a bucket is set, else local)."""
    global _model_store_singleton
    if _model_store_singleton is not None:
        return _model_store_singleton

    bucket = (os.environ.get(DATA_BUCKET_ENV) or "").strip()
    if bucket:
        prefix = os.environ.get(MODEL_PREFIX_ENV, DEFAULT_MODEL_PREFIX)
        logging.info(
            f"Dixon-Coles model store: GCS bucket '{bucket}' prefix '{prefix}'"
        )
        _model_store_singleton = _GCSModelStore(bucket, prefix, DEFAULT_MODEL_FILENAME_TEMPLATE)
    else:
        logging.info(f"Dixon-Coles model store: local folder '{MODEL_DIR}'")
        _model_store_singleton = _LocalModelStore(MODEL_DIR, DEFAULT_MODEL_FILENAME_TEMPLATE)
    return _model_store_singleton


def reset_model_store() -> None:
    """Clear the cached model store. Useful in tests after mutating env vars."""
    global _model_store_singleton
    _model_store_singleton = None


def load_and_combine_data(league_name: str,
                          required_cols: Optional[List[str]] = None,
                          data_source: Any = None) -> pd.DataFrame:
    """Load all CSVs for a league from the configured data source and concatenate them."""
    required_cols = required_cols or REQUIRED_COLS
    data_source = data_source or _get_data_source()

    df_list = []
    logging.info(f"Loading data for league: {league_name} from {data_source.location(league_name)}")
    potential_date_formats = ["%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"]

    for filename, content in data_source.iter_csvs(league_name):
        try:
            df_temp = pd.read_csv(io.BytesIO(content), usecols=required_cols)
            parsed_dates = pd.to_datetime(df_temp['Date'], errors='coerce', dayfirst=True)
            if parsed_dates.isnull().any():
                for fmt in potential_date_formats:
                    mask_to_parse = parsed_dates.isnull()
                    if not mask_to_parse.any():
                        break
                    parsed_subset = pd.to_datetime(
                        df_temp.loc[mask_to_parse, 'Date'], format=fmt, errors='coerce'
                    )
                    parsed_dates.loc[mask_to_parse] = parsed_subset
            df_temp['Date'] = parsed_dates
            if df_temp['Date'].isnull().any():
                logging.warning(
                    f"Could not parse {df_temp['Date'].isnull().sum()} date(s) in {filename}."
                )
            df_list.append(df_temp)
        except Exception as e:
            logging.warning(f"Could not load or process {filename}. Error: {e}")

    if not df_list:
        raise ValueError(f"No dataframes were successfully loaded for league {league_name}.")

    return pd.concat(df_list, ignore_index=True)


# --- 2. Data Cleaning and Preprocessing (Reusable Logic) ---
def preprocess_data(df: pd.DataFrame, league_name: str) -> Tuple[pd.DataFrame, Dict[str, int], int]:
    """Cleans data, creates team IDs, and calculates time differences for a given league's data."""
    logging.info(f"Preprocessing data for league: {league_name}")
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    initial_rows = len(df)
    df.dropna(subset=['Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG'], inplace=True)
    if len(df) < initial_rows:
        logging.info(f"Dropped {initial_rows - len(df)} rows with missing essential data.")
    if df.empty:
        raise ValueError(f"No valid rows remaining for {league_name}.")
    df['FTHG'] = df['FTHG'].astype(int)
    df['FTAG'] = df['FTAG'].astype(int)
    # pandas 3's .unique() on string columns returns a StringArray (no .sort()).
    # sorted() works on either StringArray or the legacy ndarray.
    unique_teams_cleaned = sorted(pd.concat([df['HomeTeam'], df['AwayTeam']]).unique())
    team_map = {team_name: i for i, team_name in enumerate(unique_teams_cleaned)}
    num_teams = len(team_map)
    df['HomeTeamID'] = df['HomeTeam'].map(team_map)
    df['AwayTeamID'] = df['AwayTeam'].map(team_map)
    df.sort_values(by='Date', inplace=True)
    df.reset_index(drop=True, inplace=True)
    reference_date = df['Date'].max()
    df['TimeDiff'] = (reference_date - df['Date']).dt.days
    df['TimeDiff'] = df['TimeDiff'].clip(lower=0)
    return df, team_map, num_teams


# --- 3. Model Functions (Core Logic - mostly unchanged) ---
def dixon_coles_tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    lam = max(lam, 1e-9);
    mu = max(mu, 1e-9)
    if x == 0 and y == 0: return 1.0 - rho * lam * mu
    if x == 0 and y == 1: return 1.0 + rho * mu
    if x == 1 and y == 0: return 1.0 + rho * lam
    if x == 1 and y == 1: return 1.0 - rho
    return 1.0


def calculate_dixon_coles_probs(lambda_home: float, lambda_away: float, rho: float,
                                max_goals: int = MAX_GOALS_PREDICT) -> Dict[str, Any]:
    prob_matrix = np.zeros((max_goals + 1, max_goals + 1))
    home_poisson_pmf = poisson.pmf(np.arange(max_goals + 1), lambda_home)
    away_poisson_pmf = poisson.pmf(np.arange(max_goals + 1), lambda_away)
    for hg in range(max_goals + 1):
        for ag in range(max_goals + 1):
            tau = dixon_coles_tau(hg, ag, lambda_home, lambda_away, rho)
            prob_matrix[hg, ag] = max(0.0, tau * home_poisson_pmf[hg] * away_poisson_pmf[ag])
    prob_matrix /= np.sum(prob_matrix)
    p_home_win = np.sum(np.tril(prob_matrix, k=-1))
    p_draw = np.sum(np.diag(prob_matrix))
    p_away_win = np.sum(np.triu(prob_matrix, k=1))
    max_prob_idx = np.unravel_index(np.argmax(prob_matrix, axis=None), prob_matrix.shape)
    goals_home, goals_away = np.meshgrid(np.arange(max_goals + 1), np.arange(max_goals + 1), indexing='ij')
    total_goals_matrix = goals_home + goals_away
    over_2_5_prob = np.sum(prob_matrix[total_goals_matrix > 2.5])
    btts_yes_prob = np.sum(prob_matrix[(goals_home > 0) & (goals_away > 0)])
    return {
        'probabilities_1x2': {'home_win': p_home_win, 'draw': p_draw, 'away_win': p_away_win},
        'goal_predictions': {
            'most_likely_score': f"{max_prob_idx[0]}-{max_prob_idx[1]}",
            'most_likely_score_prob': prob_matrix[max_prob_idx],
            'over_2_5_prob': over_2_5_prob, 'under_2_5_prob': 1.0 - over_2_5_prob,
            'btts_yes_prob': btts_yes_prob, 'btts_no_prob': 1.0 - btts_yes_prob
        },
        'prob_matrix': prob_matrix.tolist()  # Convert to list for JSON serialization
    }


def predict_match(home_team_name: str, away_team_name: str, estimated_params: Dict[str, Any],
                  team_map: Dict[str, int]) -> Optional[Dict[str, Any]]:
    if home_team_name not in team_map or away_team_name not in team_map:
        missing = [t for t in [home_team_name, away_team_name] if t not in team_map]
        raise TeamNotFoundError(f"Team(s) not found in model's team map: {', '.join(missing)}")
    if home_team_name == away_team_name:
        raise ValueError("Home and away team cannot be the same.")

    home_adv, rho = estimated_params['home_adv'], estimated_params['rho']
    att_ratings, def_ratings = estimated_params['attack'], estimated_params['defence']

    log_lam_home = home_adv + att_ratings[home_team_name] + def_ratings[away_team_name]
    log_lam_away = att_ratings[away_team_name] + def_ratings[home_team_name]
    lambda_home = max(0.01, math.exp(log_lam_home))
    lambda_away = max(0.01, math.exp(log_lam_away))

    prediction_results = calculate_dixon_coles_probs(lambda_home, lambda_away, rho)
    prediction_results['lambda_home'] = lambda_home
    prediction_results['lambda_away'] = lambda_away
    return prediction_results


def _dixon_coles_tau_vec(hg: np.ndarray, ag: np.ndarray, lam: np.ndarray,
                         mu: np.ndarray, rho: float) -> np.ndarray:
    """Vectorised counterpart of dixon_coles_tau, evaluated over all matches at once.

    Identical semantics to the scalar version (only the four low-score cells
    differ from 1.0); written as masked assignments so it stays branch-free.
    """
    tau = np.ones_like(lam)
    m_00 = (hg == 0) & (ag == 0)
    m_01 = (hg == 0) & (ag == 1)
    m_10 = (hg == 1) & (ag == 0)
    m_11 = (hg == 1) & (ag == 1)
    tau = np.where(m_00, 1.0 - rho * lam * mu, tau)
    tau = np.where(m_01, 1.0 + rho * mu, tau)
    tau = np.where(m_10, 1.0 + rho * lam, tau)
    tau = np.where(m_11, 1.0 - rho, tau)
    return tau


def neg_log_likelihood(params: np.ndarray, h_ids: np.ndarray, a_ids: np.ndarray,
                       hg: np.ndarray, ag: np.ndarray, t_diffs: np.ndarray,
                       loggamma_hg1: np.ndarray, loggamma_ag1: np.ndarray,
                       num_teams: int) -> float:
    """Time-weighted Dixon-Coles negative log-likelihood, fully vectorised.

    The caller pre-extracts the per-match arrays once (h_ids, a_ids, hg, ag,
    t_diffs) plus the precomputable loggamma terms, so every minimize() call
    is pure numpy with no DataFrame access — typically ~100× faster than the
    iterrows-based version it replaces.
    """
    home_adv = params[0]
    att = params[1:num_teams + 1]
    defs = params[num_teams + 1:2 * num_teams + 1]
    rho = params[2 * num_teams + 1]
    xi = FIXED_XI

    # Sum(att) = 0 constraint enforced softly at each evaluation (defence is
    # not re-centred — same as the original scalar implementation).
    att = att - att.mean()

    log_lam = home_adv + att[h_ids] + defs[a_ids]
    log_mu = att[a_ids] + defs[h_ids]
    lam = np.exp(log_lam)
    mu = np.exp(log_mu)

    tau = _dixon_coles_tau_vec(hg, ag, lam, mu, rho)
    # Same penalty as the scalar version: a single bad tau aborts the
    # evaluation with a large positive cost so the optimiser steers away.
    if np.any(tau <= 1e-12):
        return 1e10

    weights = np.exp(-xi * t_diffs)
    log_lik_per_match = (
        hg * log_lam - lam - loggamma_hg1
        + ag * log_mu - mu - loggamma_ag1
        + np.log(tau)
    )
    return -float(np.sum(weights * log_lik_per_match))


# --- 4. Optimization Setup (Reusable Logic) ---
def fit_dixon_coles_model(data: pd.DataFrame, team_map: Dict[str, int], num_teams: int, league_name: str) -> Optional[
    Dict[str, Any]]:
    logging.info(f"Starting Optimization for {league_name}...")
    num_params = 1 + 2 * num_teams + 1
    initial_params = np.concatenate([np.array([0.1]), np.zeros(num_teams * 2), np.array([-0.1])])
    bounds = [(None, None)] + [(-5.0, 5.0)] * (2 * num_teams) + [(-0.9, 0.9)]

    # Pre-extract per-match arrays once. neg_log_likelihood is called by
    # L-BFGS-B many times (once per function eval + once per gradient
    # finite-difference component) — pulling these out of the DataFrame loop
    # is the whole point of the vectorisation.
    h_ids = data['HomeTeamID'].to_numpy(dtype=np.int64)
    a_ids = data['AwayTeamID'].to_numpy(dtype=np.int64)
    hg_arr = data['FTHG'].to_numpy(dtype=np.float64)
    ag_arr = data['FTAG'].to_numpy(dtype=np.float64)
    t_diffs = data['TimeDiff'].to_numpy(dtype=np.float64)
    loggamma_hg1 = loggamma(hg_arr + 1.0)
    loggamma_ag1 = loggamma(ag_arr + 1.0)

    # L-BFGS-B uses finite-difference gradients here (no analytic jacobian),
    # so each iteration costs roughly num_params+1 likelihood evals. With
    # ~50–100 parameters per league and sub-ms per eval, generous caps are
    # cheap — they only matter as a runaway safety net.
    options = {
        'maxiter': 10000,
        'maxfun': 200000,
        'ftol': 1e-9,
        'gtol': 1e-5,
    }

    logging.info(
        f"Optimization parameters: {num_teams} teams, {len(data)} matches, {num_params} parameters"
    )

    res = minimize(
        neg_log_likelihood,
        initial_params,
        args=(h_ids, a_ids, hg_arr, ag_arr, t_diffs, loggamma_hg1, loggamma_ag1, num_teams),
        method='L-BFGS-B',
        bounds=bounds,
        options=options,
    )

    if res.success:
        logging.info(f"Optimization Successful for {league_name}!")
        params = res.x
        att_mean = np.mean(params[1:num_teams + 1])
        return {
            'home_adv': params[0],
            'attack': {k: v - att_mean for k, v in zip(team_map.keys(), params[1:num_teams + 1])},
            'defence': dict(zip(team_map.keys(), params[num_teams + 1:2 * num_teams + 1])),
            'rho': params[2 * num_teams + 1],
            'xi': FIXED_XI,
            'final_log_likelihood': -res.fun
        }
    else:
        logging.error(f"Optimization Failed for {league_name}: {res.message}")
        return None


# --- 5. API-Facing Service Functions ---

def train_model_for_league(league_name: str, force_refit: bool = False):
    """Main training orchestrator function."""
    store = _get_model_store()

    if store.model_exists(league_name) and not force_refit:
        msg = f"Model for {league_name} already exists. Training skipped."
        logging.info(msg)
        return {"status": "skipped", "message": msg, "model_path": store.location(league_name)}

    try:
        raw_data = load_and_combine_data(league_name)
        processed_data, team_mapping, n_teams = preprocess_data(raw_data, league_name)

        # Filter for completed matches before today
        today_date = datetime.date.today()
        training_data = processed_data[processed_data['Date'].dt.date < today_date].copy()
        if training_data.empty:
            raise ValueError(f"No completed matches found to train on for {league_name}.")

        estimated_params = fit_dixon_coles_model(training_data, team_mapping, n_teams, league_name)

        if estimated_params:
            model_data_to_save = {'params': estimated_params, 'team_map': team_mapping, 'num_teams': n_teams}
            payload = pickle.dumps(model_data_to_save)
            stored_at = store.save_model(league_name, payload)

            # Clear this league from cache if it exists, so the new model is loaded next time.
            # NB: this only invalidates the cache in *this* process. Multi-instance
            # Cloud Run deployments will see staleness until each instance reloads.
            if league_name in _model_cache:
                del _model_cache[league_name]

            msg = f"Model for {league_name} trained and saved successfully."
            logging.info(msg)
            return {"status": "success", "message": msg, "model_path": stored_at}
        else:
            raise RuntimeError(f"Model fitting failed for {league_name}.")

    except (DataNotFoundError, ValueError, RuntimeError) as e:
        logging.error(f"Training failed for {league_name}: {e}")
        raise e


def load_model_for_league(league_name: str) -> Tuple[Dict, Dict, int]:
    """Loads a model from the configured store, using an in-memory cache."""
    # 1. Check cache first
    if league_name in _model_cache:
        logging.info(f"Loading model for '{league_name}' from cache.")
        return _model_cache[league_name]

    # 2. If not in cache, fetch from the store
    store = _get_model_store()
    logging.info(f"Loading model for '{league_name}' from {store.location(league_name)}")
    try:
        payload = store.load_model(league_name)
        saved_data = pickle.loads(payload)

        params = saved_data['params']
        team_map = saved_data['team_map']
        num_teams = saved_data['num_teams']

        # 3. Store in cache for future requests
        _model_cache[league_name] = (params, team_map, num_teams)

        return params, team_map, num_teams
    except ModelNotFoundError:
        raise
    except Exception as e:
        logging.error(f"Failed to load or parse model for {league_name}. Error: {e}")
        raise ModelNotFoundError(f"Could not load model for {league_name}.")


def get_prediction(league_name: str, home_team: str, away_team: str) -> Dict:
    """API-facing function to get a match prediction."""
    estimated_params, team_mapping, _ = load_model_for_league(league_name)
    prediction = predict_match(home_team, away_team, estimated_params, team_mapping)
    return prediction


def get_teams_for_league(league_name: str) -> List[str]:
    """Returns a sorted list of teams for a given league model."""
    _, team_mapping, _ = load_model_for_league(league_name)
    return sorted(list(team_mapping.keys()))


def list_available_models() -> List[str]:
    """Returns a list of leagues for which a trained model is available."""
    return _get_model_store().list_models()
