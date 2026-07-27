from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from redis.exceptions import RedisError
from rq.job import Job

from app.config import get_settings
from app.logging_config import configure_logging
from app.metrics import observe_http_request, record_scan_queued, render_metrics
from app.queueing import get_queue, get_redis
from app.redaction import redact_url_query
from app.schemas import (
    ScanCreated,
    ScanRequest,
    ScanState,
    ScanStatusResponse,
)
from app.services.ml import get_model_service
from app.services.url_guard import UnsafeTargetError, normalize_url
from app.tasks import execute_scan

BASE_DIR = Path(__file__).resolve().parent
settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="DOM XSS Pipeline",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "").strip()
    if supplied:
        return supplied[:100]
    return str(uuid.uuid4())


@app.middleware("http")
async def security_headers(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    content_length = request.headers.get("content-length")
    try:
        body_size = int(content_length) if content_length else 0
    except ValueError:
        body_size = 16_385
    if body_size > 16_384:
        response: Response = JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={"detail": "request body is too large"},
        )
    else:
        response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    )
    return response


@app.middleware("http")
async def request_observability(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = _request_id(request)
    request.state.request_id = request_id
    started_at = time.perf_counter()
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        logger.exception(
            "request failed",
            extra={
                "request_id": request_id,
                "status_code": status_code,
                "request_host": request.url.hostname or "",
            },
        )
        raise
    finally:
        duration_seconds = time.perf_counter() - started_at
        observe_http_request(
            request.method,
            request.url.path,
            status_code,
            duration_seconds,
        )
        logger.info(
            "request completed",
            extra={
                "request_id": request_id,
                "status_code": status_code,
                "duration_ms": round(duration_seconds * 1000, 2),
                "request_host": request.url.hostname or "",
            },
        )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "ml_threshold": settings.ml_threshold,
            "zap_enabled": settings.zap_enabled,
        },
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    try:
        get_redis().ping()
        get_model_service()
    except Exception as exc:
        logger.exception("readiness check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"not ready: {type(exc).__name__}",
        ) from exc
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    payload, content_type = render_metrics()
    return Response(content=payload, headers={"Content-Type": content_type})


@app.post(
    "/api/scans",
    response_model=ScanCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_scan(scan_request: ScanRequest, request: Request) -> ScanCreated:
    if scan_request.dynamic_verification and not settings.zap_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "dynamic verification is not enabled; start the application "
                "with the ZAP Compose override"
            ),
        )

    try:
        normalized = normalize_url(scan_request.target_url)
    except UnsafeTargetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    payload = scan_request.model_dump(mode="json")
    payload["target_url"] = normalized

    try:
        queue = get_queue()
        if queue.count >= settings.max_queued_scans:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="scan queue is at capacity; try again later",
                headers={"Retry-After": "30"},
            )
        job = queue.enqueue(
            execute_scan,
            payload,
            job_timeout=settings.scan_job_timeout_seconds,
            result_ttl=settings.result_ttl_seconds,
            failure_ttl=settings.result_ttl_seconds,
            description=f"DOM XSS scan: {redact_url_query(normalized)}",
        )
        record_scan_queued()
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="scan queue is unavailable",
        ) from exc

    logger.info(
        "scan queued",
        extra={
            "request_id": str(getattr(request.state, "request_id", ""))[:100],
            "job_id": job.id,
            "target_host": urlsplit(normalized).hostname or "",
            "scope_mode": scan_request.scope_mode.value,
            "status": "queued",
        },
    )
    return ScanCreated(
        job_id=job.id,
        status_url=str(request.url_for("scan_status", job_id=job.id)),
    )


def _state_from_job(job: Job) -> ScanState:
    raw_status = job.get_status(refresh=True)
    status_value = getattr(raw_status, "value", raw_status)
    try:
        return ScanState(str(status_value))
    except ValueError:
        return ScanState.unknown


@app.get(
    "/api/scans/{job_id}",
    response_model=ScanStatusResponse,
    name="scan_status",
)
async def scan_status(job_id: str) -> ScanStatusResponse:
    if len(job_id) > 100:
        raise HTTPException(status_code=404, detail="scan not found")

    try:
        job = Job.fetch(job_id, connection=get_redis())
    except Exception as exc:
        raise HTTPException(status_code=404, detail="scan not found") from exc

    state = _state_from_job(job)
    meta = job.get_meta(refresh=True)
    error: str | None = None
    result: dict[str, Any] | None = None

    if state == ScanState.finished and isinstance(job.result, dict):
        result = job.result
    elif state == ScanState.failed:
        error = "scan failed"

    return ScanStatusResponse(
        job_id=job.id,
        state=state,
        progress=int(meta.get("progress", 0)),
        stage=str(meta.get("stage", "")),
        result=result,
        error=error,
    )
