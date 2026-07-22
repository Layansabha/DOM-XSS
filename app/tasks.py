from __future__ import annotations

import asyncio
from typing import Any

from rq import get_current_job

from app.config import get_settings
from app.schemas import ScanRequest
from app.services.pipeline import run_pipeline


def _set_progress(progress: int, stage: str) -> None:
    job = get_current_job()
    if job is None:
        return
    job.meta["progress"] = progress
    job.meta["stage"] = stage
    job.save_meta()


def execute_scan(payload: dict[str, Any]) -> dict[str, object]:
    request = ScanRequest.model_validate(payload)
    settings = get_settings()
    _set_progress(1, "validating")
    return asyncio.run(run_pipeline(request, settings, _set_progress))
