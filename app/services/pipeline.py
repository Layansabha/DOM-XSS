from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict

import httpx

from app.config import Settings
from app.redaction import redact_url_queries
from app.schemas import ScanRequest
from app.services.crawler import BrowserCrawler
from app.services.ml import get_model_service
from app.services.security_features import FEATURE_CONTRACT
from app.services.url_guard import RequestPolicy, infer_scope_mode, normalize_url
from app.services.zap import ZapClient, ZapScanError

ProgressCallback = Callable[[int, str], None]


async def run_pipeline(
    request: ScanRequest,
    settings: Settings,
    progress: ProgressCallback,
) -> dict[str, object]:
    if request.dynamic_verification and not settings.zap_enabled:
        raise RuntimeError("dynamic verification was requested but ZAP is not enabled")

    started_at = time.time()
    normalized_target = normalize_url(request.target_url)
    scope_mode = (
        infer_scope_mode(normalized_target)
        if request.scope_mode.value == "auto"
        else request.scope_mode.value
    )

    policy = RequestPolicy(settings)
    normalized_target = await policy.validate(normalized_target)

    progress(10, "crawling")
    crawler = BrowserCrawler(settings, policy)
    page_artifacts = await crawler.crawl(normalized_target, scope_mode)

    progress(55, "ml-inference")
    model = get_model_service()
    pages: list[dict[str, object]] = []

    for artifact in page_artifacts:
        page_result = artifact.public_metadata()
        if not artifact.rendered_dom and not artifact.javascript:
            page_result["ml"] = {
                "status": "not_scored",
                "reason": "no content was collected",
            }
        else:
            prediction = model.predict(artifact.rendered_dom, artifact.javascript)
            if prediction is None:
                page_result["ml"] = {
                    "status": "not_scored",
                    "reason": "no executable JavaScript units were found",
                }
            else:
                ml_payload: dict[str, object] = asdict(prediction)
                if prediction.status == "insufficient_feature_coverage":
                    ml_payload["reason"] = (
                        "collected code did not match the model vocabulary"
                    )
                page_result["ml"] = ml_payload
        pages.append(page_result)

    zap_result: dict[str, object] | None = None
    if request.dynamic_verification:
        progress(70, "dynamic-verification")
        zap = ZapClient(settings)
        try:
            zap_scan = await zap.verify(
                normalized_target,
                scope_mode,
                discovered_urls=[artifact.url for artifact in page_artifacts],
            )
            zap_result = {"status": "completed", **asdict(zap_scan)}
        except (ZapScanError, httpx.HTTPError, OSError, TimeoutError) as exc:
            zap_result = {
                "status": "failed",
                "error": redact_url_queries(f"{type(exc).__name__}: {exc}"),
                "alerts": [],
                "confirmed_alert_count": 0,
                "warnings": [],
            }
        finally:
            await zap.close()

    progress(95, "finalizing")
    scored_pages: list[dict[str, object]] = []
    high_priority_page_count = 0
    model_high_risk_page_count = 0
    for page in pages:
        ml_result = page.get("ml")
        if not isinstance(ml_result, dict) or ml_result.get("status") != "scored":
            continue
        scored_pages.append(page)
        if bool(ml_result.get("vulnerable")):
            high_priority_page_count += 1
        if bool(ml_result.get("model_high_priority")):
            model_high_risk_page_count += 1
    zap_alerts = (zap_result or {}).get("alerts", [])
    alert_count = len(zap_alerts) if isinstance(zap_alerts, list) else 0
    raw_confirmed_alert_count = (zap_result or {}).get("confirmed_alert_count", 0)
    confirmed_alert_count = (
        raw_confirmed_alert_count if isinstance(raw_confirmed_alert_count, int) else 0
    )

    result: dict[str, object] = {
        "target_url": normalized_target,
        "scope_mode": scope_mode,
        "dynamic_verification": request.dynamic_verification,
        "summary": {
            "pages_collected": len(page_artifacts),
            "pages_scored": len(scored_pages),
            "high_priority_pages": high_priority_page_count,
            "ml_high_risk_pages": model_high_risk_page_count,
            "zap_dom_xss_findings": alert_count,
            "verified_dom_xss_alerts": confirmed_alert_count,
        },
        "pages": pages,
        "zap": zap_result,
        "model": {
            "algorithm": "LightGBM",
            "feature_contract": FEATURE_CONTRACT,
            "decision_policy": "model threshold OR static source/sink co-occurrence signal",
            "threshold": settings.ml_threshold,
        },
        "duration_seconds": round(time.time() - started_at, 2),
        "disclaimer": (
            "The ML score is a ranking signal, not a calibrated probability of exploitation. "
            "Static source/sink co-occurrence raises investigation priority but does not prove "
            "data flow or exploitability. "
            "Only ZAP active-rule findings are labeled confirmed; client-side rule findings "
            "still require reproducible evidence and human review."
        ),
    }
    progress(100, "finished")
    return result
