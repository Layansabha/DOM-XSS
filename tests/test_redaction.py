from __future__ import annotations

import json
import logging
import sys

from app.logging_config import JsonFormatter
from app.redaction import redact_url_queries, redact_url_query


def test_redact_url_query_preserves_location_without_secrets() -> None:
    redacted = redact_url_query(
        "https://example.com/assets/app.js?token=secret&signature=private#fragment"
    )

    assert redacted == "https://example.com/assets/app.js"
    assert "secret" not in redacted
    assert "signature" not in redacted


def test_redact_url_queries_handles_urls_inside_error_text() -> None:
    redacted = redact_url_queries(
        "request failed for https://example.com/path?token=secret "
        "after https://cdn.example.com/app.js?v=42"
    )

    assert redacted == (
        "request failed for https://example.com/path "
        "after https://cdn.example.com/app.js"
    )


def test_redact_url_queries_preserves_surrounding_punctuation() -> None:
    redacted = redact_url_queries(
        "failed (https://example.com/path?token=secret), retry."
    )

    assert redacted == "failed (https://example.com/path), retry."


def test_json_formatter_redacts_message_and_exception_urls() -> None:
    try:
        raise RuntimeError("fetch failed: https://example.com/path?token=secret")
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="scan failed for https://example.com/?api_key=secret",
        args=(),
        exc_info=exc_info,
    )
    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "scan failed for https://example.com/"
    assert "secret" not in payload["exception"]
    assert "https://example.com/path" in payload["exception"]
