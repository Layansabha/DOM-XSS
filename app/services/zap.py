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
    confirmed_alert_count: int
    client_spider_ran: bool
    warnings: list[str]
    scanner_id: str = "40026"


class ZapClient:
    DOM_XSS_SCANNER_ID = "40026"
    CLIENT_DOM_SCANNER_IDS = {
        "210000",
        "210001",
        "210016",
        "210017",
        "210018",
        "220000",
        "220003",
        "220004",
        "220005",
        "220008",
        "220009",
        "40101",
        "40102",
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.zap_base_url.rstrip("/"),
            timeout=settings.request_timeout_seconds,
            trust_env=False,
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

    async def _wait_for_passive_scan(self, deadline: float) -> None:
        while time.monotonic() < deadline:
            payload = await self._request("pscan", "view", "recordsToScan")
            if int(str(payload.get("recordsToScan", "0"))) <= 0:
                return
            await asyncio.sleep(1)
        raise ZapScanError("ZAP passive scan timed out")

    async def _create_context(self, target_url: str, context_name: str) -> str:
        created = await self._request(
            "context",
            "action",
            "newContext",
            contextName=context_name,
        )
        context_id = str(created.get("contextId", ""))
        if not context_id:
            raise ZapScanError(f"ZAP did not return a context id: {created}")

        parsed = urlsplit(target_url)
        host = re.escape(parsed.hostname or "")
        port = parsed.port
        default_port = 443 if parsed.scheme == "https" else 80
        port_expression = f":{port}" if port else rf"(?::{default_port})?"
        include_regex = rf"^{re.escape(parsed.scheme)}://{host}{port_expression}/.*$"
        await self._request(
            "context",
            "action",
            "includeInContext",
            contextName=context_name,
            regex=include_regex,
        )
        await self._request(
            "context",
            "action",
            "setContextInScope",
            contextName=context_name,
            booleanInScope="true",
        )
        return context_id

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

    async def _stop_scan(self, component: str, scan_id: str) -> None:
        if not scan_id:
            return
        try:
            await self._request(component, "action", "stop", scanId=scan_id)
        except (httpx.HTTPError, ZapScanError) as exc:
            logger.debug("ZAP could not stop %s scan %s: %s", component, scan_id, exc)

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
        scan_id = ""
        client_scan_id = ""
        client_spider_ran = False
        warnings: list[str] = []

        try:
            context_id = await self._create_context(target_url, context_name)
            await self._configure_policy(policy_name)

            try:
                client_scan = await self._request(
                    "clientSpider",
                    "action",
                    "scan",
                    browser="firefox-headless",
                    url=target_url,
                    contextName=context_name,
                    subtreeOnly="true" if scope_mode == "page" else "false",
                    maxCrawlDepth=0 if scope_mode == "page" else self.settings.max_crawl_depth,
                    pageLoadTime=min(self.settings.request_timeout_seconds, 20),
                    actionWaitTime=1,
                    numberOfBrowsers=1,
                )
                client_scan_id = str(client_scan.get("scan", ""))
                if not client_scan_id:
                    raise ZapScanError(f"ZAP did not start the Client Spider: {client_scan}")
                client_deadline = min(
                    deadline,
                    time.monotonic() + max(30, self.settings.zap_max_minutes * 24),
                )
                await self._wait_for_percentage(
                    "clientSpider",
                    client_scan_id,
                    client_deadline,
                )
                client_spider_ran = True
                client_scan_id = ""
                await self._wait_for_passive_scan(client_deadline)
            except (httpx.HTTPError, ZapScanError, ValueError) as exc:
                warnings.append(
                    "Client Spider was unavailable or incomplete; "
                    f"active DOM XSS verification continued ({type(exc).__name__})"
                )
                await self._stop_scan("clientSpider", client_scan_id)
                client_scan_id = ""

            seed_urls = (
                [target_url] if scope_mode == "page" else [target_url, *(discovered_urls or [])]
            )
            seen_seed_urls: set[str] = set()
            for seed_url in seed_urls:
                if len(seen_seed_urls) >= self.settings.max_pages:
                    break
                if seed_url in seen_seed_urls:
                    continue
                try:
                    if not same_origin(target_url, seed_url):
                        continue
                except ValueError:
                    continue
                seen_seed_urls.add(seed_url)
                access = await self._request(
                    "core",
                    "action",
                    "accessUrl",
                    url=seed_url,
                    followRedirects="true",
                )
                if "accessUrl" not in access:
                    raise ZapScanError(f"ZAP could not access {seed_url}")
                scan = await self._request(
                    "ascan",
                    "action",
                    "scan",
                    url=seed_url,
                    recurse="false",
                    inScopeOnly="true",
                    scanPolicyName=policy_name,
                    method="",
                    postData="",
                    contextId=context_id,
                )
                scan_id = str(scan.get("scan", ""))
                if not scan_id:
                    raise ZapScanError(f"ZAP did not start the active scan: {scan}")
                await self._wait_for_percentage("ascan", scan_id, deadline)
                scan_id = ""

            try:
                await self._wait_for_passive_scan(deadline)
            except (httpx.HTTPError, ZapScanError, ValueError) as exc:
                warnings.append(f"passive scan queue did not finish ({type(exc).__name__})")

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
            seen_alerts: set[tuple[str, str, str, str, str]] = set()
            for raw_alert in raw_alerts:
                if not isinstance(raw_alert, dict):
                    continue
                plugin_id = str(raw_alert.get("pluginId", ""))
                alert_url = str(raw_alert.get("url", ""))
                if (
                    plugin_id != self.DOM_XSS_SCANNER_ID
                    and plugin_id not in self.CLIENT_DOM_SCANNER_IDS
                ):
                    continue
                if alert_url:
                    try:
                        if not same_origin(target_url, alert_url):
                            continue
                    except ValueError:
                        continue
                name = str(raw_alert.get("name", "DOM XSS"))
                param = str(raw_alert.get("param", ""))
                evidence = str(raw_alert.get("evidence", ""))
                fingerprint = (plugin_id, alert_url, name, param, evidence)
                if fingerprint in seen_alerts:
                    continue
                seen_alerts.add(fingerprint)
                confirmed = plugin_id == self.DOM_XSS_SCANNER_ID
                alerts.append(
                    {
                        "name": name,
                        "risk": raw_alert.get("risk", ""),
                        "confidence": raw_alert.get("confidence", ""),
                        "url": alert_url,
                        "param": param,
                        "attack": raw_alert.get("attack", ""),
                        "evidence": evidence,
                        "description": raw_alert.get("description", ""),
                        "solution": raw_alert.get("solution", ""),
                        "reference": raw_alert.get("reference", ""),
                        "plugin_id": plugin_id,
                        "finding_type": "active_confirmation" if confirmed else "client_rule",
                        "confirmed": confirmed,
                    }
                )

            return ZapResult(
                alerts=alerts,
                scanned_url=target_url,
                policy_name=policy_name,
                confirmed_alert_count=sum(bool(alert["confirmed"]) for alert in alerts),
                client_spider_ran=client_spider_ran,
                warnings=warnings,
            )
        finally:
            await self._stop_scan("clientSpider", client_scan_id)
            await self._stop_scan("ascan", scan_id)
            await self._cleanup(context_name, policy_name)
