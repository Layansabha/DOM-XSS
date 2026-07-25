from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, SummaryMetricFamily
from redis.exceptions import RedisError
from rq import Worker

logger = logging.getLogger(__name__)

METRICS_KEY = "domxss:operational-metrics"

HTTP_REQUESTS = Counter(
    "dom_xss_http_requests",
    "HTTP requests handled by the API.",
    labelnames=("method", "path", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "dom_xss_http_request_duration_seconds",
    "HTTP request latency observed by the API.",
    labelnames=("method", "path"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


def _decode_metric(raw: dict[Any, Any], field: str) -> float:
    value = raw.get(field.encode())
    if value is None:
        value = raw.get(field)
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class RedisOperationalCollector:
    def collect(self) -> Iterator[object]:
        availability = GaugeMetricFamily(
            "dom_xss_operational_metrics_redis_available",
            "Whether operational metrics can be read from Redis.",
        )
        try:
            from app.queueing import get_queue, get_redis

            redis_client = get_redis()
            redis_client.ping()
            values = redis_client.hgetall(METRICS_KEY)
            queue_depth = float(get_queue().count)
            worker_count = float(len(Worker.all(connection=redis_client)))
        except (RedisError, OSError, ValueError):
            availability.add_metric([], 0.0)
            yield availability
            return

        availability.add_metric([], 1.0)
        yield availability

        queue = GaugeMetricFamily("dom_xss_queue_depth", "Jobs waiting in the scan queue.")
        queue.add_metric([], queue_depth)
        yield queue

        workers = GaugeMetricFamily("dom_xss_workers", "Registered RQ workers.")
        workers.add_metric([], worker_count)
        yield workers

        counters = (
            ("dom_xss_scans_queued", "Scans accepted by the API.", "scans_queued"),
            (
                "dom_xss_scans_completed",
                "Scans completed successfully.",
                "scans_completed",
            ),
            ("dom_xss_scans_failed", "Scans that failed in the worker.", "scans_failed"),
            ("dom_xss_pages_collected", "Pages collected across completed scans.", "pages_collected"),
            ("dom_xss_zap_failures", "Dynamic-verification runs that failed.", "zap_failures"),
        )
        for name, description, field in counters:
            metric = CounterMetricFamily(name, description)
            metric.add_metric([], _decode_metric(values, field))
            yield metric

        duration = SummaryMetricFamily(
            "dom_xss_scan_duration_seconds",
            "End-to-end worker scan duration.",
        )
        duration.add_metric(
            [],
            count_value=_decode_metric(values, "scan_duration_count"),
            sum_value=_decode_metric(values, "scan_duration_sum"),
        )
        yield duration


REGISTRY.register(RedisOperationalCollector())


def normalize_metric_path(path: str) -> str:
    if path.startswith("/api/scans/"):
        return "/api/scans/{job_id}"
    if path.startswith("/static/"):
        return "/static"
    return path


def observe_http_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    if path == "/metrics":
        return
    metric_path = normalize_metric_path(path)
    HTTP_REQUESTS.labels(method=method, path=metric_path, status=str(status_code)).inc()
    HTTP_REQUEST_DURATION.labels(method=method, path=metric_path).observe(duration_seconds)


def _increment(field: str, amount: int = 1) -> None:
    try:
        from app.queueing import get_redis

        get_redis().hincrby(METRICS_KEY, field, amount)
    except RedisError:
        logger.warning("failed to update operational metric", extra={"status": field})


def _increment_float(field: str, amount: float) -> None:
    try:
        from app.queueing import get_redis

        get_redis().hincrbyfloat(METRICS_KEY, field, amount)
    except RedisError:
        logger.warning("failed to update operational metric", extra={"status": field})


def record_scan_queued() -> None:
    _increment("scans_queued")


def record_scan_completed(result: dict[str, object], duration_seconds: float) -> None:
    _increment("scans_completed")
    _increment("scan_duration_count")
    _increment_float("scan_duration_sum", duration_seconds)

    summary = result.get("summary")
    if isinstance(summary, dict):
        pages_collected = summary.get("pages_collected", 0)
        if isinstance(pages_collected, int) and pages_collected > 0:
            _increment("pages_collected", pages_collected)

    zap_result = result.get("zap")
    if isinstance(zap_result, dict) and zap_result.get("status") == "failed":
        _increment("zap_failures")


def record_scan_failed(duration_seconds: float) -> None:
    _increment("scans_failed")
    _increment("scan_duration_count")
    _increment_float("scan_duration_sum", duration_seconds)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
