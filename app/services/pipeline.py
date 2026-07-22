from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict

import httpx

from app.config import Settings
from app.schemas import ScanRequest
from app.services.crawler import BrowserCrawler
from app.services.ml import get_model_service
from app.services.url_guard import RequestPolicy, infer_scope_mode, normalize_url
from app.services.zap import ZapClient, ZapScanError

ProgressCallback = Callable[[int, str], None]


async def run_pipeline(
    request: ScanRequest,
    settings: Settings,
    progress: ProgressCallback,
) -> dict[str, object]:
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
                page_result["ml"] = {
                    "status": "scored",
                    **asdict(prediction),
                }
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
                "error": f"{type(exc).__name__}: {exc}",
                "alerts": [],
            }
        finally:
            await zap.close()

    progress(95, "finalizing")
    scored_pages: list[dict[str, object]] = []
    high_risk_page_count = 0
    for page in pages:
        ml_result = page.get("ml")
        if not isinstance(ml_result, dict) or ml_result.get("status") != "scored":
            continue
        scored_pages.append(page)
        if bool(ml_result.get("vulnerable")):
            high_risk_page_count += 1
    verified_alerts = (zap_result or {}).get("alerts", [])
    alert_count = len(verified_alerts) if isinstance(verified_alerts, list) else 0

    result: dict[str, object] = {
        "target_url": normalized_target,
        "scope_mode": scope_mode,
        "dynamic_verification": request.dynamic_verification,
        "summary": {
            "pages_collected": len(page_artifacts),
            "pages_scored": len(scored_pages),
            "ml_high_risk_pages": high_risk_page_count,
            "verified_dom_xss_alerts": alert_count,
        },
        "pages": pages,
        "zap": zap_result,
        "model": {
            "algorithm": "LightGBM",
            "feature_contract": "function-ast-bag-of-words-v1",
            "threshold": settings.ml_threshold,
        },
        "duration_seconds": round(time.time() - started_at, 2),
        "disclaimer": (
            "ML output is a triage signal. A vulnerability should be considered "
            "confirmed only when reproducible evidence is available."
        ),
    }
    progress(100, "finished")
    return result
