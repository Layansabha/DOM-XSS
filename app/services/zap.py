from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.services.url_guard import same_origin

logger = logging.getLogger(__name__)


class ZapScanError(RuntimeError):
    pass


@dataclass(frozen=True)
class ZapResult:
    alerts: list[dict[str, object]]
    scanned_url: str
    policy_name: str
    scanner_id: str = "40026"


class ZapClient:
    DOM_XSS_SCANNER_ID = "40026"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.zap_base_url.rstrip("/"),
            timeout=settings.request_timeout_seconds,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(
        self,
        component: str,
        message_type: str,
        name: str,
        **params: str | int | float | bool | None,
    ) -> dict[str, object]:
        query: dict[str, str | int | float | bool | None] = {
            "apikey": self.settings.zap_api_key,
            **params,
        }
        response = await self.client.get(
            f"/JSON/{component}/{message_type}/{name}/",
            params=query,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ZapScanError("unexpected ZAP API response")
        if "code" in payload and "message" in payload:
            raise ZapScanError(str(payload.get("message", "ZAP API error")))
        return payload

    async def _wait_for_percentage(
        self,
        component: str,
        scan_id: str,
        deadline: float,
    ) -> None:
        while time.monotonic() < deadline:
            payload = await self._request(
                component,
                "view",
                "status",
                scanId=scan_id,
            )
            status = int(str(payload.get("status", "0")))
            if status >= 100:
                return
            await asyncio.sleep(2)
        raise ZapScanError(f"{component} timed out")

    async def _create_context(self, target_url: str, context_name: str) -> None:
        await self._request(
            "context",
            "action",
            "newContext",
            contextName=context_name,
        )

        parsed = urlsplit(target_url)
        host = re.escape(parsed.hostname or "")
        port = parsed.port
        default_port = 443 if parsed.scheme == "https" else 80
        port_expression = f":{port}" if port else rf"(?::{default_port})?"
        include_regex = (
            rf"^{re.escape(parsed.scheme)}://{host}{port_expression}/.*$"
        )
        await self._request(
            "context",
            "action",
            "includeInContext",
            contextName=context_name,
            regex=include_regex,
        )

    async def _configure_policy(self, policy_name: str) -> None:
        try:
            await self._request(
                "ascan",
                "action",
                "removeScanPolicy",
                scanPolicyName=policy_name,
            )
        except (httpx.HTTPError, ZapScanError) as exc:
            logger.debug("scan policy did not exist before creation: %s", exc)

        await self._request(
            "ascan",
            "action",
            "addScanPolicy",
            scanPolicyName=policy_name,
        )
        await self._request(
            "ascan",
            "action",
            "disableAllScanners",
            scanPolicyName=policy_name,
        )
        await self._request(
            "ascan",
            "action",
            "enableScanners",
            ids=self.DOM_XSS_SCANNER_ID,
            scanPolicyName=policy_name,
        )
        await self._request(
            "ascan",
            "action",
            "setScannerAttackStrength",
            id=self.DOM_XSS_SCANNER_ID,
            attackStrength=self.settings.zap_attack_strength.upper(),
            scanPolicyName=policy_name,
        )
        await self._request(
            "ascan",
            "action",
            "setScannerAlertThreshold",
            id=self.DOM_XSS_SCANNER_ID,
            alertThreshold=self.settings.zap_alert_threshold.upper(),
            scanPolicyName=policy_name,
        )

    async def _cleanup(self, context_name: str, policy_name: str) -> None:
        for component, action, params in (
            ("context", "removeContext", {"contextName": context_name}),
            ("ascan", "removeScanPolicy", {"scanPolicyName": policy_name}),
        ):
            try:
                await self._request(component, "action", action, **params)
            except (httpx.HTTPError, ZapScanError) as exc:
                logger.debug("ZAP cleanup failed for %s: %s", action, exc)

    async def verify(
        self,
        target_url: str,
        scope_mode: str,
        discovered_urls: list[str] | None = None,
    ) -> ZapResult:
        if not self.settings.zap_api_key:
            raise ZapScanError("ZAP_API_KEY is not configured")

        suffix = secrets.token_hex(5)
        context_name = f"domxss-{suffix}"
        policy_name = f"domxss-only-{suffix}"
        deadline = time.monotonic() + self.settings.zap_max_minutes * 60

        try:
            await self._create_context(target_url, context_name)
            await self._configure_policy(policy_name)

            seed_urls = [target_url, *(discovered_urls or [])]
            seen_seed_urls: set[str] = set()
            for seed_url in seed_urls:
                if seed_url in seen_seed_urls:
                    continue
                seen_seed_urls.add(seed_url)
                try:
                    if not same_origin(target_url, seed_url):
                        continue
                except ValueError:
                    continue
                access = await self._request(
                    "core",
                    "action",
                    "accessUrl",
                    url=seed_url,
                    followRedirects="true",
                )
                if "accessUrl" not in access:
                    raise ZapScanError(f"ZAP could not access {seed_url}")

            if scope_mode == "domain":
                spider = await self._request(
                    "spider",
                    "action",
                    "scan",
                    url=target_url,
                    maxChildren=str(self.settings.max_pages),
                    recurse="true",
                    contextName=context_name,
                    subtreeOnly="true",
                )
                spider_id = str(spider.get("scan", ""))
                if spider_id:
                    await self._wait_for_percentage("spider", spider_id, deadline)

            scan = await self._request(
                "ascan",
                "action",
                "scan",
                url=target_url,
                recurse="true" if scope_mode == "domain" else "false",
                inScopeOnly="true",
                scanPolicyName=policy_name,
                method="",
                postData="",
                contextId="",
            )
            scan_id = str(scan.get("scan", ""))
            if not scan_id:
                raise ZapScanError(f"ZAP did not start the active scan: {scan}")
            await self._wait_for_percentage("ascan", scan_id, deadline)

            alert_payload = await self._request(
                "core",
                "view",
                "alerts",
                baseurl=target_url,
                start="0",
                count="5000",
                riskId="",
            )
            raw_alerts = alert_payload.get("alerts", [])
            if not isinstance(raw_alerts, list):
                raw_alerts = []

            alerts: list[dict[str, object]] = []
            for raw_alert in raw_alerts:
                if not isinstance(raw_alert, dict):
                    continue
                plugin_id = str(raw_alert.get("pluginId", ""))
                alert_url = str(raw_alert.get("url", ""))
                if plugin_id != self.DOM_XSS_SCANNER_ID:
                    continue
                if alert_url:
                    try:
                        if not same_origin(target_url, alert_url):
                            continue
                    except ValueError:
                        continue
                alerts.append(
                    {
                        "name": raw_alert.get("name", "DOM XSS"),
                        "risk": raw_alert.get("risk", ""),
                        "confidence": raw_alert.get("confidence", ""),
                        "url": alert_url,
                        "param": raw_alert.get("param", ""),
                        "attack": raw_alert.get("attack", ""),
                        "evidence": raw_alert.get("evidence", ""),
                        "description": raw_alert.get("description", ""),
                        "solution": raw_alert.get("solution", ""),
                        "reference": raw_alert.get("reference", ""),
                        "plugin_id": plugin_id,
                    }
                )

            return ZapResult(
                alerts=alerts,
                scanned_url=target_url,
                policy_name=policy_name,
            )
        finally:
            await self._cleanup(context_name, policy_name)
