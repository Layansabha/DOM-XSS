from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.crawler import (
    BrowserCrawler,
    PageArtifact,
    canonicalize_link,
    collection_status_from_warnings,
    is_safe_crawl_link,
    merge_script_nodes,
    script_nodes_from_html,
    summarize_warnings,
)
from app.services.url_guard import UnsafeTargetError


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
    assert collection_status_from_warnings(
        ["Chromium runtime source collection failed: AttributeError"]
    ) == "partial"
    assert collection_status_from_warnings(["page collection failed: TimeoutError"]) == "failed"
    assert artifact.public_metadata()["collection_status"] == "partial"


def test_original_html_scripts_survive_runtime_dom_replacement() -> None:
    nodes = script_nodes_from_html(
        """
        <script>document.write(location.hash)</script>
        <script type="application/json">{"not": "javascript"}</script>
        <script src="/assets/app.js"></script>
        """,
        "https://example.com/path/page",
    )

    assert nodes == [
        {"src": "", "text": "document.write(location.hash)"},
        {"src": "https://example.com/assets/app.js", "text": ""},
    ]


def test_script_node_merge_deduplicates_original_live_and_resource_entries() -> None:
    merged = merge_script_nodes(
        [{"src": "https://example.com/app.js", "text": ""}],
        [
            {"src": "https://example.com/app.js", "text": ""},
            {"src": "", "text": "run()"},
        ],
        [{"src": "", "text": "run()"}],
    )

    assert merged == [
        {"src": "https://example.com/app.js", "text": ""},
        {"src": "", "text": "run()"},
    ]


def test_script_node_merge_prefers_runtime_source_over_url_only_node() -> None:
    merged = merge_script_nodes(
        [{"src": "https://example.com/app.js", "text": ""}],
        [{"src": "https://example.com/app.js", "text": "function run() {}"}],
    )

    assert merged == [
        {"src": "https://example.com/app.js", "text": "function run() {}"},
    ]


@pytest.mark.asyncio
async def test_route_guard_blocks_a_redirect_rejected_by_policy() -> None:
    class RejectingPolicy:
        async def validate(self, url: str) -> str:
            raise UnsafeTargetError("redirect resolved to a private address")

    class RecordingRoute:
        request = SimpleNamespace(url="https://redirect.example/path?token=secret")
        aborted_with: str | None = None
        continued = False

        async def abort(self, reason: str) -> None:
            self.aborted_with = reason

        async def continue_(self) -> None:
            self.continued = True

    route = RecordingRoute()
    crawler = BrowserCrawler(Settings(_env_file=None), RejectingPolicy())  # type: ignore[arg-type]

    await crawler._route_guard(route)  # type: ignore[arg-type]

    assert route.aborted_with == "blockedbyclient"
    assert route.continued is False


@pytest.mark.asyncio
async def test_runtime_script_event_handler_ignores_non_mapping_events() -> None:
    class RecordingSession:
        callback: object | None = None

        def on(self, event: str, callback: object) -> None:
            assert event == "Debugger.scriptParsed"
            self.callback = callback

        async def send(self, method: str) -> dict[str, object]:
            assert method == "Debugger.enable"
            return {}

        async def detach(self) -> None:
            pass

    session = RecordingSession()
    context = SimpleNamespace(new_cdp_session=lambda page: None)

    async def new_cdp_session(page: object) -> RecordingSession:
        return session

    context.new_cdp_session = new_cdp_session
    crawler = BrowserCrawler(Settings(_env_file=None), SimpleNamespace())

    returned_session, parsed = await crawler._start_runtime_script_collection(  # type: ignore[arg-type]
        context,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )
    callback = session.callback
    assert callable(callback)
    callback(None)
    callback({"scriptId": "7", "url": "https://example.com/app.js"})

    assert returned_session is session
    assert parsed == [{"scriptId": "7", "url": "https://example.com/app.js"}]


@pytest.mark.asyncio
async def test_runtime_script_collection_rejects_invalid_cdp_payloads_without_crashing() -> None:
    class StubSession:
        async def send(
            self,
            method: str,
            params: dict[str, str],
        ) -> dict[str, str] | None:
            assert method == "Debugger.getScriptSource"
            if params["scriptId"] == "1":
                return None
            return {"scriptSource": "function sink() { document.write(location.hash); }"}

    crawler = BrowserCrawler(Settings(_env_file=None), SimpleNamespace())
    parsed_scripts = [
        None,
        {"scriptId": "1", "url": "https://example.com/invalid.js"},
        {"scriptId": "2", "url": "https://example.com/app.js"},
    ]

    nodes, warnings = await crawler._finish_runtime_script_collection(  # type: ignore[arg-type]
        StubSession(),  # type: ignore[arg-type]
        parsed_scripts,  # type: ignore[arg-type]
    )

    assert nodes == [
        {
            "src": "https://example.com/app.js",
            "text": "function sink() { document.write(location.hash); }",
        }
    ]
    assert warnings == ["Chromium runtime source could not be read (2 occurrences)"]


@pytest.mark.asyncio
async def test_runtime_script_setup_failure_detaches_session() -> None:
    class FailingSession:
        detached = False

        def on(self, event: str, callback: object) -> None:
            pass

        async def send(self, method: str) -> dict[str, object]:
            raise AttributeError("unexpected CDP response")

        async def detach(self) -> None:
            self.detached = True

    session = FailingSession()

    async def new_cdp_session(page: object) -> FailingSession:
        return session

    context = SimpleNamespace(new_cdp_session=new_cdp_session)
    crawler = BrowserCrawler(Settings(_env_file=None), SimpleNamespace())

    with pytest.raises(AttributeError, match="unexpected CDP response"):
        await crawler._start_runtime_script_collection(  # type: ignore[arg-type]
            context,  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
        )

    assert session.detached is True
