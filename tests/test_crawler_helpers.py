from __future__ import annotations

from app.services.crawler import canonicalize_link, is_safe_crawl_link


def test_canonicalize_link_removes_fragment() -> None:
    assert canonicalize_link("https://example.com/a/", "../b#section") == "https://example.com/b"


def test_canonicalize_link_rejects_non_http_and_credentials() -> None:
    assert canonicalize_link("https://example.com", "mailto:test@example.com") is None
    assert canonicalize_link("https://example.com", "https://u:p@example.com/") is None


def test_safe_crawl_link_skips_destructive_and_binary_paths() -> None:
    assert not is_safe_crawl_link("https://example.com/logout")
    assert not is_safe_crawl_link("https://example.com/reports/result.pdf")
    assert is_safe_crawl_link("https://example.com/docs/getting-started")
