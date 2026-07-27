from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException, Request

import app.main as main
from app.schemas import ScanRequest


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "scheme": "https",
            "server": ("scanner.example", 443),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
            "path": "/api/scans",
            "raw_path": b"/api/scans",
            "query_string": b"",
            "headers": [],
        }
    )


@pytest.mark.asyncio
async def test_index_returns_security_headers_and_request_id() -> None:
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_request_body_limit_is_enforced_before_endpoint_processing() -> None:
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/scans",
            content=b"",
            headers={"content-length": "16385"},
        )

    assert response.status_code == 413
    assert response.json() == {"detail": "request body is too large"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_create_scan_rejects_zap_when_not_enabled() -> None:
    with pytest.raises(HTTPException) as caught:
        await main.create_scan(
            ScanRequest(
                target_url="https://example.com/",
                scope_mode="auto",
                dynamic_verification=True,
            ),
            _request(),
        )

    assert caught.value.status_code == 422
    assert caught.value.detail == (
        "dynamic verification is not enabled; start the application "
        "with the ZAP Compose override"
    )


@pytest.mark.asyncio
async def test_create_scan_rejects_when_queue_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = SimpleNamespace(count=main.settings.max_queued_scans)
    monkeypatch.setattr(main, "get_queue", lambda: queue)

    with pytest.raises(HTTPException) as caught:
        await main.create_scan(
            ScanRequest(
                target_url="https://example.com/",
                scope_mode="auto",
                dynamic_verification=False,
            ),
            _request(),
        )

    assert caught.value.status_code == 429
    assert caught.value.headers == {"Retry-After": "30"}
    assert caught.value.detail == "scan queue is at capacity; try again later"


@pytest.mark.asyncio
async def test_failed_scan_status_does_not_expose_exception_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = SimpleNamespace(
        id="job-1",
        result=None,
        exc_info="RuntimeError: https://example.com/path?token=secret",
        get_status=lambda refresh: "failed",
        get_meta=lambda refresh: {},
    )
    monkeypatch.setattr(main, "get_redis", lambda: object())
    monkeypatch.setattr(
        main.Job,
        "fetch",
        staticmethod(lambda job_id, connection: job),
    )

    response = await main.scan_status("job-1")

    assert response.state == "failed"
    assert response.error == "scan failed"
    assert "secret" not in response.error
