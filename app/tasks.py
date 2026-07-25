from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlsplit

from rq import get_current_job

from app.config import get_settings
from app.logging_config import configure_logging
from app.metrics import record_scan_completed, record_scan_failed
from app.schemas import ScanRequest
from app.services.pipeline import run_pipeline

configure_logging(get_settings().log_level)
logger = logging.getLogger(__name__)


def _job_id() -> str:
    job = get_current_job()
    return job.id if job is not None else ""


def _set_progress(progress: int, stage: str) -> None:
    job = get_current_job()
    if job is None:
        return
    job.meta["progress"] = progress
    job.meta["stage"] = stage
    job.save_meta()
    logger.info(
        "scan stage changed",
        extra={
            "job_id": job.id,
            "stage": stage,
            "status": "running",
        },
    )


def execute_scan(payload: dict[str, Any]) -> dict[str, object]:
    request = ScanRequest.model_validate(payload)
    settings = get_settings()
    started_at = time.perf_counter()
    job_id = _job_id()
    target_host = urlsplit(request.target_url).hostname or ""

    logger.info(
        "scan started",
        extra={
            "job_id": job_id,
            "target_host": target_host,
            "scope_mode": request.scope_mode.value,
            "status": "running",
        },
    )
    _set_progress(1, "validating")

    try:
        result = asyncio.run(run_pipeline(request, settings, _set_progress))
    except Exception as exc:
        duration_seconds = time.perf_counter() - started_at
        record_scan_failed(duration_seconds)
        logger.exception(
            "scan failed",
            extra={
                "job_id": job_id,
                "target_host": target_host,
                "scope_mode": request.scope_mode.value,
                "status": "failed",
                "duration_seconds": round(duration_seconds, 3),
                "error_type": type(exc).__name__,
            },
        )
        raise

    duration_seconds = time.perf_counter() - started_at
    record_scan_completed(result, duration_seconds)
    logger.info(
        "scan completed",
        extra={
            "job_id": job_id,
            "target_host": target_host,
            "scope_mode": request.scope_mode.value,
            "status": "completed",
            "duration_seconds": round(duration_seconds, 3),
        },
    )
    return result
