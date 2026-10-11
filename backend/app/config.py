"""Runtime settings, read once from the environment (and backend/.env if present)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
load_dotenv(REPO_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    nws_user_agent: str = os.environ.get(
        "NWS_USER_AGENT", "ClosureCall-HackMidwest2026 (set NWS_USER_AGENT to your contact)"
    )
    demo_mode: bool = _bool("DEMO_MODE")
    # Unreviewed past decisions get an AI review this many days after their decision day.
    review_after_days: int = int(os.environ.get("REVIEW_AFTER_DAYS", "7"))
    db_path: Path = Path(os.environ.get("DATABASE_PATH", BACKEND_DIR / "var" / "closurecall.db"))
    cache_dir: Path = Path(os.environ.get("HTTP_CACHE_DIR", BACKEND_DIR / "fixtures" / "http_cache"))
    live_ttl_seconds: int = int(os.environ.get("LIVE_CACHE_TTL_SECONDS", "600"))
    snapshot_stale_seconds: int = int(os.environ.get("SNAPSHOT_STALE_SECONDS", "600"))
    refresh_interval_seconds: int = int(os.environ.get("REFRESH_INTERVAL_SECONDS", "0"))

    # Akamai workshop inference first; Strands on Bedrock is the secondary path.
    model_provider: str = os.environ.get("MODEL_PROVIDER", "akamai").strip().lower()
    akamai_api_key: str = os.environ.get("AKAMAI_API_KEY", "")
    akamai_base_url: str = "https://ws.akamai-workshops.com/v1"
    akamai_model_id: str = "hackathon-chat"
    strands_fallback_enabled: bool = _bool("STRANDS_FALLBACK_ENABLED", True)
    strands_model_id: str = os.environ.get(
        "STRANDS_MODEL_ID", os.environ.get("AWS_BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
    )
    aws_region: str = os.environ.get("AWS_REGION", "us-east-1")

    # Akamai Object Storage (S3-compatible). Leave the bucket or keys empty to keep everything local.
    obj_endpoint: str = os.environ.get("OBJ_ENDPOINT", "https://us-ord-1.linodeobjects.com")
    obj_region: str = os.environ.get("OBJ_REGION", "us-ord-1")
    obj_bucket: str = os.environ.get("OBJ_BUCKET", "")
    obj_access_key: str = os.environ.get("OBJ_ACCESS_KEY", "")
    obj_secret_key: str = os.environ.get("OBJ_SECRET_KEY", "")
    obj_prefix: str = os.environ.get("OBJ_PREFIX", "")  # folder inside the bucket; e.g. "dev" for local runs
    # Load the frozen backtesting dataset from the bucket's shared datasets/ folder when missing locally.
    dataset_auto_restore: bool = _bool("DATASET_AUTO_RESTORE", True)
    dataset_version: str = os.environ.get("DATASET_VERSION", "ames-forecast-v1")
    obj_backup_hours: float = float(os.environ.get("OBJ_BACKUP_HOURS", "24"))

    demo_reference_now = None  # set at runtime in DEMO_MODE (see app.snapshots.demo_live_as_of)

    data_dir: Path = BACKEND_DIR / "data"
    config_dir: Path = BACKEND_DIR / "config"
    fixtures_dir: Path = BACKEND_DIR / "fixtures"


settings = Settings()
