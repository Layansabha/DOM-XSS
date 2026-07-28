from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections.abc import Sequence
from typing import Any
from urllib.parse import urljoin

import httpx

VERSION = "1.0.0"
TERMINAL_STATES = {"finished", "failed", "stopped", "canceled"}


class CliError(RuntimeError):
    """Expected command-line error with a user-facing message."""


class Console:
    def __init__(self, *, color: bool, quiet: bool = False) -> None:
        self.color = color and sys.stdout.isatty()
        self.quiet = quiet

    def _style(self, value: str, code: str) -> str:
        return f"\033[{code}m{value}\033[0m" if self.color else value

    def blue(self, value: str) -> str:
        return self._style(value, "34")

    def green(self, value: str) -> str:
        return self._style(value, "32")

    def yellow(self, value: str) -> str:
        return self._style(value, "33")

    def red(self, value: str) -> str:
        return self._style(value, "31")

    def bold(self, value: str) -> str:
        return self._style(value, "1")

    def write(self, value: str = "") -> None:
        if not self.quiet:
            print(value)

    def progress(self, value: str) -> None:
        if not self.quiet:
            print(value, file=sys.stderr)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="domxss",
        description="Submit and inspect DOM XSS analysis jobs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:8000",
        help="pipeline API base URL (default: %(default)s)",
    )
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")

    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser("scan", help="submit a new analysis")
    scan.add_argument("target", help="authorized HTTP(S) URL to analyze")
    scan.add_argument(
        "--scope",
        choices=("auto", "domain", "page"),
        default="auto",
        help="collection scope (default: %(default)s)",
    )
    scan.add_argument(
        "--verify",
        action="store_true",
        help="request OWASP ZAP verification (requires the ZAP profile)",
    )
    scan.add_argument(
        "--detach",
        action="store_true",
        help="print the job ID without waiting for completion",
    )
    scan.add_argument("--json", action="store_true", help="write the final result as JSON")
    scan.add_argument(
        "--timeout",
        type=float,
        default=900,
        metavar="SECONDS",
        help="maximum wait time (default: %(default)s)",
    )
    scan.add_argument(
        "--poll-interval",
        type=float,
        default=1.5,
        metavar="SECONDS",
        help="status poll interval (default: %(default)s)",
    )
    scan.add_argument(
        "--fail-on-high-risk",
        action="store_true",
        help="exit with status 2 when the model marks a page high priority",
    )

    status = commands.add_parser("status", help="read an existing job")
    status.add_argument("job_id")
    status.add_argument("--wait", action="store_true", help="wait for a terminal state")
    status.add_argument("--json", action="store_true", help="write the response as JSON")
    status.add_argument("--timeout", type=float, default=900, metavar="SECONDS")
    status.add_argument("--poll-interval", type=float, default=1.5, metavar="SECONDS")

    commands.add_parser("health", help="check API, Redis, and model readiness")
    return parser


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise CliError(f"API returned invalid JSON (HTTP {response.status_code})") from exc
    if not isinstance(payload, dict):
        raise CliError(f"API returned an unexpected response (HTTP {response.status_code})")
    if response.is_error:
        detail = payload.get("detail") or payload.get("error") or response.reason_phrase
        if isinstance(detail, list):
            detail = "; ".join(str(item.get("msg", item)) for item in detail)
        raise CliError(f"API request failed (HTTP {response.status_code}): {detail}")
    return payload


def _job_url(api_url: str, job_id: str) -> str:
    return urljoin(f"{api_url.rstrip('/')}/", f"api/scans/{job_id}")


def _wait_for_job(
    client: httpx.Client,
    status_url: str,
    *,
    timeout: float,
    poll_interval: float,
    console: Console,
) -> dict[str, Any]:
    if timeout <= 0:
        raise CliError("--timeout must be greater than zero")
    if poll_interval <= 0:
        raise CliError("--poll-interval must be greater than zero")

    deadline = time.monotonic() + timeout
    last_line = ""
    while True:
        payload = _response_payload(client.get(status_url))
        state = str(payload.get("state", "unknown"))
        progress = int(payload.get("progress", 0))
        stage = str(payload.get("stage") or "")
        line = f"[{progress:3d}%] {state:<9} {stage}".rstrip()
        if line != last_line:
            console.progress(line)
            last_line = line

        if state in TERMINAL_STATES:
            return payload
        if time.monotonic() >= deadline:
            raise CliError(f"job did not finish within {timeout:g} seconds")
        time.sleep(poll_interval)


def _percentage(value: object) -> str:
    if not isinstance(value, (int, float, str)):
        return "n/a"
    try:
        return f"{float(value) * 100:.1f}%"
    except ValueError:
        return "n/a"


def _truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return f"{value[: width - 1]}…"


def _render_result(result: dict[str, Any], console: Console) -> None:
    summary = result.get("summary") or {}
    pages = result.get("pages") or []
    duration = result.get("duration_seconds", "n/a")

    console.write(console.bold("ANALYSIS COMPLETE"))
    console.write(
        "  ".join(
            (
                f"pages {summary.get('pages_collected', 0)}",
                f"scored {summary.get('pages_scored', 0)}",
                f"high-risk {summary.get('ml_high_risk_pages', 0)}",
                f"confirmed {summary.get('verified_dom_xss_alerts', 0)}",
                f"duration {duration}s",
            )
        )
    )
    console.write()

    if not pages:
        console.write(console.yellow("No pages were collected."))
        return

    terminal_width = max(72, shutil.get_terminal_size((100, 24)).columns)
    url_width = max(24, terminal_width - 39)
    console.write(f"{'PRIORITY':<10} {'SCORE':<8} {'COVERAGE':<10} PAGE")
    console.write(f"{'─' * 8:<10} {'─' * 6:<8} {'─' * 8:<10} {'─' * min(url_width, 40)}")

    for page in pages:
        ml = page.get("ml") or {}
        status = str(ml.get("status", "not_scored"))
        if status == "scored":
            high_risk = bool(ml.get("vulnerable"))
            priority = console.red("HIGH") if high_risk else console.green("LOW")
            score = _percentage(ml.get("risk_score"))
        else:
            priority = console.yellow("REVIEW")
            score = "n/a"
        coverage = _percentage(ml.get("feature_coverage"))
        page_url = _truncate(str(page.get("url", "")), url_width)
        console.write(f"{priority:<10} {score:<8} {coverage:<10} {page_url}")

        collection_status = str(page.get("collection_status", "complete"))
        if collection_status != "complete":
            console.write(f"  collection={collection_status}")
        for warning in page.get("warnings") or []:
            console.write(f"  warning: {warning}")

    console.write()
    console.write("ML scores rank findings; they do not prove exploitability.")


def _render_job(payload: dict[str, Any], console: Console, *, as_json: bool) -> None:
    if as_json:
        console.write(json.dumps(payload, indent=2, sort_keys=True))
        return

    state = str(payload.get("state", "unknown"))
    if state == "finished" and isinstance(payload.get("result"), dict):
        _render_result(payload["result"], console)
        return

    console.write(f"job       {payload.get('job_id', 'unknown')}")
    console.write(f"state     {state}")
    console.write(f"progress  {payload.get('progress', 0)}%")
    if payload.get("stage"):
        console.write(f"stage     {payload['stage']}")
    if payload.get("error"):
        console.write(f"error     {payload['error']}")


def _scan_exit_code(payload: dict[str, Any], *, fail_on_high_risk: bool) -> int:
    if str(payload.get("state")) != "finished":
        return 1
    if not fail_on_high_risk:
        return 0
    result = payload.get("result") or {}
    summary = result.get("summary") or {}
    return 2 if int(summary.get("ml_high_risk_pages", 0)) > 0 else 0


def _run(args: argparse.Namespace, console: Console) -> int:
    api_url = str(args.api_url).rstrip("/")
    timeout = float(getattr(args, "timeout", 30))
    with httpx.Client(timeout=httpx.Timeout(30, connect=10)) as client:
        if args.command == "health":
            payload = _response_payload(client.get(f"{api_url}/readyz"))
            console.write(console.green(f"ready: {payload.get('status', 'ready')}"))
            return 0

        if args.command == "status":
            status_url = _job_url(api_url, args.job_id)
            payload = (
                _wait_for_job(
                    client,
                    status_url,
                    timeout=timeout,
                    poll_interval=args.poll_interval,
                    console=console,
                )
                if args.wait
                else _response_payload(client.get(status_url))
            )
            _render_job(payload, console, as_json=args.json)
            return 0 if str(payload.get("state")) not in {"failed", "stopped", "canceled"} else 1

        response = client.post(
            f"{api_url}/api/scans",
            json={
                "target_url": args.target,
                "scope_mode": args.scope,
                "dynamic_verification": args.verify,
            },
        )
        created = _response_payload(response)
        job_id = str(created.get("job_id", ""))
        if not job_id:
            raise CliError("API response did not include a job ID")
        status_url = str(created.get("status_url") or _job_url(api_url, job_id))

        if args.detach:
            if args.json:
                console.write(json.dumps(created, indent=2, sort_keys=True))
            else:
                console.write(f"job queued  {job_id}")
                console.write(f"status      domxss status {job_id} --wait")
            return 0

        progress_console = Console(color=not args.no_color, quiet=args.json)
        payload = _wait_for_job(
            client,
            status_url,
            timeout=timeout,
            poll_interval=args.poll_interval,
            console=progress_console,
        )
        _render_job(payload, console, as_json=args.json)
        return _scan_exit_code(payload, fail_on_high_risk=args.fail_on_high_risk)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    console = Console(color=not args.no_color)
    try:
        return _run(args, console)
    except (CliError, httpx.HTTPError) as exc:
        print(f"domxss: error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("domxss: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
