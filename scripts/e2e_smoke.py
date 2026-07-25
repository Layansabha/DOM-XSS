from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

API_BASE = "http://127.0.0.1:8000"
TARGET_URL = "http://test-target:8081/"
TIMEOUT_SECONDS = 120


def _request_json(url: str, payload: dict[str, object] | None = None) -> dict[str, Any]:
    data = None
    headers: dict[str, str] = {}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8")


def main() -> int:
    created = _request_json(
        f"{API_BASE}/api/scans",
        {
            "target_url": TARGET_URL,
            "scope_mode": "page",
            "dynamic_verification": False,
        },
    )
    status_url = str(created["status_url"])
    deadline = time.monotonic() + TIMEOUT_SECONDS
    previous_stage = ""

    while time.monotonic() < deadline:
        status = _request_json(status_url)
        stage = str(status.get("stage", ""))
        if stage != previous_stage:
            print(
                f"state={status.get('state')} stage={stage} progress={status.get('progress')}",
                flush=True,
            )
            previous_stage = stage

        state = status.get("state")
        if state == "finished":
            result = status.get("result")
            if not isinstance(result, dict):
                raise AssertionError("finished job did not return a result")
            summary = result.get("summary")
            if not isinstance(summary, dict):
                raise AssertionError("scan result is missing its summary")
            if int(summary.get("pages_collected", 0)) < 1:
                raise AssertionError("end-to-end scan did not collect a page")
            if result.get("scope_mode") != "page":
                raise AssertionError("end-to-end scan returned an unexpected scope")

            metrics = _request_text(f"{API_BASE}/metrics")
            required_metrics = (
                "dom_xss_queue_depth",
                "dom_xss_workers",
                "dom_xss_scans_completed_total",
                "dom_xss_scan_duration_seconds_sum",
            )
            missing = [name for name in required_metrics if name not in metrics]
            if missing:
                raise AssertionError(f"metrics endpoint is missing: {', '.join(missing)}")

            print(json.dumps(summary, sort_keys=True), flush=True)
            return 0
        if state == "failed":
            raise AssertionError(f"end-to-end scan failed: {status.get('error')}")
        time.sleep(2)

    raise TimeoutError(f"scan did not finish within {TIMEOUT_SECONDS} seconds")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, TimeoutError, KeyError, ValueError, urllib.error.URLError) as exc:
        print(f"E2E failure: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
