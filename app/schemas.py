from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScopeMode(StrEnum):
    auto = "auto"
    domain = "domain"
    page = "page"


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_url: str = Field(min_length=4, max_length=2048)
    scope_mode: ScopeMode = ScopeMode.auto
    dynamic_verification: bool = False


class ScanCreated(BaseModel):
    job_id: str
    status_url: str


class ScanState(StrEnum):
    queued = "queued"
    started = "started"
    deferred = "deferred"
    scheduled = "scheduled"
    finished = "finished"
    failed = "failed"
    stopped = "stopped"
    canceled = "canceled"
    unknown = "unknown"


class ScanStatusResponse(BaseModel):
    job_id: str
    state: ScanState
    progress: int = Field(default=0, ge=0, le=100)
    stage: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
