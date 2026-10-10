from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "FirstLight"
    environment: str = "development"
    database_url: str = f"sqlite:///{ROOT / 'firstlight.db'}"
    valkey_url: str | None = None
    nws_user_agent: str = "FirstLight-HackMidwest/0.1 (contact@example.invalid)"
    request_timeout_seconds: float = 15.0
    poll_interval_seconds: int = 600
    evidence_max_age_minutes: int = 30
    object_storage_endpoint: str | None = None
    object_storage_bucket: str = "firstlight-evidence"
    object_storage_region: str = "us-ord"
    object_storage_access_key: str | None = None
    object_storage_secret_key: str | None = None
    object_storage_local_dir: Path = ROOT / "data" / "evidence"
    inference_base_url: str | None = Field(default=None, alias="AKAMAI_INFERENCE_BASE_URL")
    inference_api_key: str | None = Field(default=None, alias="AKAMAI_INFERENCE_API_KEY")
    inference_model: str = Field(
        default="firstlight-organizer-model", alias="AKAMAI_INFERENCE_MODEL"
    )
    embedding_model: str = Field(
        default="firstlight-embedding-model", alias="AKAMAI_EMBEDDING_MODEL"
    )
    enable_real_sends: bool = False
    allowed_send_recipients: str = ""
    frontend_origin: str = "http://localhost:5173"
    demo_mode: bool = True

    @property
    def allowlist(self) -> set[str]:
        return {item.strip() for item in self.allowed_send_recipients.split(",") if item.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
