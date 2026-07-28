from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CURRENT_MODEL_PATH = Path("/app/artifacts/lightgbm_grouped_model.txt")
CURRENT_VOCAB_PATH = Path("/app/artifacts/vocab_top500_grouped.json")
LEGACY_MODEL_PATH = Path("/app/artifacts/lightgbm_model.txt")
LEGACY_VOCAB_PATH = Path("/app/artifacts/vocab_top500_filtered.json")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    log_level: str = "INFO"

    redis_url: str = "redis://redis:6379/0"
    queue_name: str = "domxss"
    max_queued_scans: int = Field(default=25, ge=1, le=1000)
    result_ttl_seconds: int = Field(default=86400, ge=300, le=604800)
    scan_job_timeout_seconds: int = Field(default=1800, ge=60, le=7200)

    allow_private_targets: bool = False
    max_pages: int = Field(default=30, ge=1, le=200)
    max_crawl_depth: int = Field(default=2, ge=0, le=5)
    crawl_delay_ms: int = Field(default=150, ge=0, le=5000)
    request_timeout_seconds: int = Field(default=20, ge=5, le=120)
    max_page_bytes: int = Field(default=5_000_000, ge=100_000, le=25_000_000)
    max_script_bytes: int = Field(default=2_000_000, ge=50_000, le=10_000_000)
    include_third_party_scripts: bool = False
    user_agent: str = "DOM-XSS-Pipeline/1.0"

    ml_model_path: Path = CURRENT_MODEL_PATH
    ml_vocab_path: Path = CURRENT_VOCAB_PATH
    ml_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    ml_max_code_units: int = Field(default=500, ge=1, le=5000)
    ml_max_code_unit_bytes: int = Field(default=250_000, ge=1_000, le=2_000_000)

    zap_enabled: bool = False
    zap_base_url: str = "http://zap:8080"
    zap_api_key: str = ""
    zap_max_minutes: int = Field(default=10, ge=1, le=60)
    zap_attack_strength: str = "LOW"
    zap_alert_threshold: str = "MEDIUM"

    @model_validator(mode="after")
    def migrate_legacy_artifact_paths(self) -> Settings:
        """Keep existing .env files working after the grouped-model upgrade."""
        if self.ml_model_path == LEGACY_MODEL_PATH:
            self.ml_model_path = CURRENT_MODEL_PATH
        if self.ml_vocab_path == LEGACY_VOCAB_PATH:
            self.ml_vocab_path = CURRENT_VOCAB_PATH
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
