from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

import app.main as main
from app.schemas import ScanRequest


@pytest.mark.asyncio
async def test_create_scan_rejects_when_queue_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = SimpleNamespace(count=main.settings.max_queued_scans)
    monkeypatch.setattr(main, "get_queue", lambda: queue)
    request = Request(
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

    with pytest.raises(HTTPException) as caught:
        await main.create_scan(
            ScanRequest(
                target_url="https://example.com/",
                scope_mode="auto",
                dynamic_verification=False,
            ),
            request,
        )

    assert caught.value.status_code == 429
    assert caught.value.headers == {"Retry-After": "30"}
    assert caught.value.detail == "scan queue is at capacity; try again later"
