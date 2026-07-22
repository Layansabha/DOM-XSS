from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services.zap import ZapClient


@pytest.mark.asyncio
async def test_zap_verifies_only_collected_same_origin_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        zap_api_key="test-key",
        max_pages=2,
        zap_max_minutes=1,
    )
    client = ZapClient(settings)
    calls: list[tuple[str, str, str, dict[str, Any]]] = []
    next_scan_id = 0

    async def fake_request(
        component: str,
        message_type: str,
        name: str,
        **params: Any,
    ) -> dict[str, object]:
        nonlocal next_scan_id
        calls.append((component, message_type, name, params))
        if (component, name) == ("context", "newContext"):
            return {"contextId": "7"}
        if (component, name) == ("core", "accessUrl"):
            return {"accessUrl": params["url"]}
        if (component, name) == ("clientSpider", "scan"):
            return {"scan": "client-1"}
        if (component, name) == ("ascan", "scan"):
            next_scan_id += 1
            return {"scan": str(next_scan_id)}
        if name == "status":
            return {"status": "100"}
        if (component, name) == ("core", "alerts"):
            return {
                "alerts": [
                    {
                        "pluginId": "40026",
                        "url": "https://example.com/account",
                        "name": "DOM XSS",
                    },
                    {
                        "pluginId": "220000",
                        "url": "https://example.com/settings",
                        "name": "DOM-based XSS",
                    },
                    {"pluginId": "40026", "url": "https://other.example/x"},
                    {"pluginId": "10000", "url": "https://example.com/"},
                ]
            }
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    try:
        result = await client.verify(
            "https://example.com/",
            "domain",
            discovered_urls=[
                "https://example.com/account",
                "https://example.com/settings",
                "https://other.example/x",
            ],
        )
    finally:
        await client.close()

    active_scans = [
        params for component, _, name, params in calls if (component, name) == ("ascan", "scan")
    ]
    assert [scan["url"] for scan in active_scans] == [
        "https://example.com/",
        "https://example.com/account",
    ]
    assert all(scan["recurse"] == "false" for scan in active_scans)
    assert all(scan["contextId"] == "7" for scan in active_scans)
    client_scans = [
        params
        for component, _, name, params in calls
        if (component, name) == ("clientSpider", "scan")
    ]
    assert len(client_scans) == 1
    assert client_scans[0]["contextName"].startswith("domxss-")
    assert result.client_spider_ran
    assert len(result.alerts) == 2
    assert result.alerts[0]["plugin_id"] == "40026"
    assert result.alerts[0]["confirmed"] is True
    assert result.alerts[1]["plugin_id"] == "220000"
    assert result.alerts[1]["confirmed"] is False
    assert result.confirmed_alert_count == 1
