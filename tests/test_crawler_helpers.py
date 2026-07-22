from __future__ import annotations

from app.services.crawler import (
    PageArtifact,
    canonicalize_link,
    collection_status_from_warnings,
    is_safe_crawl_link,
    summarize_warnings,
)


def test_canonicalize_link_removes_fragment() -> None:
    assert canonicalize_link("https://example.com/a/", "../b#section") == "https://example.com/b"


def test_canonicalize_link_rejects_non_http_and_credentials() -> None:
    assert canonicalize_link("https://example.com", "mailto:test@example.com") is None
    assert canonicalize_link("https://example.com", "https://u:p@example.com/") is None


def test_safe_crawl_link_skips_destructive_and_binary_paths() -> None:
    assert not is_safe_crawl_link("https://example.com/logout")
    assert not is_safe_crawl_link("https://example.com/reports/result.pdf")
    assert is_safe_crawl_link("https://example.com/docs/getting-started")


def test_summarize_warnings_collapses_duplicates_in_first_seen_order() -> None:
    warnings = [
        "network did not become idle before collection",
        "script URL was invalid and was skipped",
        "script URL was invalid and was skipped",
        "script URL was invalid and was skipped",
    ]

    assert summarize_warnings(warnings) == [
        "network did not become idle before collection",
        "script URL was invalid and was skipped (3 occurrences)",
    ]


def test_network_idle_timeout_marks_public_result_partial() -> None:
    warning = "network did not become idle before collection"
    artifact = PageArtifact(
        url="https://example.com/",
        title="Example",
        rendered_dom="<html></html>",
        javascript="",
        links_found=0,
        scripts_found=0,
        warnings=[warning],
    )

    assert collection_status_from_warnings([]) == "complete"
    assert collection_status_from_warnings([warning]) == "partial"
    assert collection_status_from_warnings(["page collection failed: TimeoutError"]) == "failed"
    assert artifact.public_metadata()["collection_status"] == "partial"
