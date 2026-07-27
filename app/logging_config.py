from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from app.redaction import redact_url_queries

_CONTEXT_FIELDS = (
    "request_id",
    "job_id",
    "stage",
    "status",
    "status_code",
    "duration_ms",
    "duration_seconds",
    "request_host",
    "target_host",
    "scope_mode",
    "error_type",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_url_queries(record.getMessage()),
        }
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = redact_url_queries(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    level_value = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level_value, handlers=[handler], force=True)
