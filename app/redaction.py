from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_HTTP_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?)]}"


def redact_url_query(url: str) -> str:
    """Remove query and fragment data while preserving a useful URL location."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "[invalid URL]"
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return "[invalid URL]"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))


def redact_url_queries(text: str) -> str:
    """Remove query data from HTTP(S) URLs embedded in warnings or log messages."""
    def replace(match: re.Match[str]) -> str:
        matched_url = match.group(0)
        stripped_url = matched_url.rstrip(_TRAILING_PUNCTUATION)
        suffix = matched_url[len(stripped_url) :]
        return f"{redact_url_query(stripped_url)}{suffix}"

    return _HTTP_URL.sub(replace, text)
