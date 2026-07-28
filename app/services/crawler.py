from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter, deque
from dataclasses import asdict, dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from bs4.element import Tag
from playwright.async_api import BrowserContext, CDPSession, Page, Route, async_playwright

from app.config import Settings
from app.redaction import redact_url_query
from app.services.url_guard import RequestPolicy, UnsafeTargetError, same_origin

logger = logging.getLogger(__name__)

_SKIP_PATH_RE = re.compile(
    r"(?:^|/)(?:logout|log-out|signout|sign-out|delete|remove|unsubscribe)(?:/|$)",
    re.IGNORECASE,
)
_SKIP_EXTENSIONS = {
    ".7z",
    ".avi",
    ".bin",
    ".css",
    ".csv",
    ".doc",
    ".docx",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".json",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".rar",
    ".svg",
    ".tar",
    ".webp",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
}

_NETWORK_IDLE_WARNING = "network did not become idle before collection"
_EXECUTABLE_SCRIPT_TYPES = {
    "application/ecmascript",
    "application/javascript",
    "module",
    "text/ecmascript",
    "text/javascript",
}


def summarize_warnings(warnings: list[str]) -> list[str]:
    """Collapse identical warnings while preserving their first-seen order."""
    counts = Counter(warnings)
    return [
        warning if counts[warning] == 1 else f"{warning} ({counts[warning]} occurrences)"
        for warning in dict.fromkeys(warnings)
    ]


def collection_status_from_warnings(warnings: list[str]) -> str:
    if any(warning.startswith("page collection failed:") for warning in warnings):
        return "failed"
    if warnings:
        return "partial"
    return "complete"


def is_safe_crawl_link(url: str) -> bool:
    parsed = urlsplit(url)
    path = parsed.path.lower()
    if _SKIP_PATH_RE.search(path):
        return False
    return not any(path.endswith(extension) for extension in _SKIP_EXTENSIONS)


@dataclass
class PageArtifact:
    url: str
    title: str
    rendered_dom: str
    javascript: str
    links_found: int
    scripts_found: int
    warnings: list[str]

    def public_metadata(self) -> dict[str, object]:
        data = asdict(self)
        data.pop("rendered_dom")
        data.pop("javascript")
        data["warnings"] = summarize_warnings(self.warnings)
        data["collection_status"] = collection_status_from_warnings(self.warnings)
        return data


def canonicalize_link(base_url: str, href: str) -> str | None:
    absolute = urljoin(base_url, href)
    parsed = urlsplit(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None

    path = parsed.path or "/"
    normalized = parsed._replace(path=path, fragment="")
    return urlunsplit(normalized)


def script_nodes_from_html(html: str, base_url: str) -> list[dict[str, str]]:
    """Read scripts from the original response before runtime DOM mutations remove them."""
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    base_tag = soup.find("base", href=True)
    effective_base_url = (
        urljoin(base_url, str(base_tag.get("href"))) if isinstance(base_tag, Tag) else base_url
    )
    nodes: list[dict[str, str]] = []
    for script in soup.find_all("script"):
        script_type = str(script.get("type", "")).split(";", 1)[0].strip().lower()
        if script_type and script_type not in _EXECUTABLE_SCRIPT_TYPES:
            continue
        raw_source = script.get("src")
        if raw_source:
            nodes.append({"src": urljoin(effective_base_url, str(raw_source)), "text": ""})
        else:
            nodes.append({"src": "", "text": str(script.string or script.get_text())})
    return nodes


def merge_script_nodes(*node_groups: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    source_indexes: dict[str, int] = {}
    for group in node_groups:
        for node in group:
            normalized = {
                "src": str(node.get("src", "")),
                "text": str(node.get("text", "")),
            }
            fingerprint = (normalized["src"], normalized["text"])
            if not any(fingerprint) or fingerprint in seen:
                continue
            source = normalized["src"]
            if source and source in source_indexes:
                existing_index = source_indexes[source]
                existing = merged[existing_index]
                if not existing["text"] and normalized["text"]:
                    seen.discard((existing["src"], existing["text"]))
                    merged[existing_index] = normalized
                    seen.add(fingerprint)
                continue
            seen.add(fingerprint)
            if source:
                source_indexes[source] = len(merged)
            merged.append(normalized)
    return merged


class BrowserCrawler:
    def __init__(self, settings: Settings, policy: RequestPolicy) -> None:
        self.settings = settings
        self.policy = policy

    async def _route_guard(self, route: Route) -> None:
        request = route.request
        if request.url.startswith(("data:", "blob:", "about:")):
            await route.continue_()
            return
        try:
            await self.policy.validate(request.url)
        except UnsafeTargetError:
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def _extract_scripts(
        self,
        context: BrowserContext,
        page: Page,
        target_origin_url: str,
        original_html: str,
        runtime_script_nodes: list[dict[str, str]],
    ) -> tuple[str, int, list[str]]:
        live_script_nodes = await page.locator("script").evaluate_all(
            """nodes => nodes
                .filter(node => {
                    const type = (node.type || "").split(";", 1)[0].trim().toLowerCase();
                    return !type || type === "module" || type.includes("javascript") ||
                        type.includes("ecmascript");
                })
                .map(node => ({
                    src: node.src || "",
                    text: node.src ? "" : (node.textContent || "")
                }))"""
        )
        loaded_script_urls = await page.evaluate(
            """() => performance.getEntriesByType('resource')
                .filter(entry => entry.initiatorType === 'script')
                .map(entry => entry.name)"""
        )
        original_script_nodes = script_nodes_from_html(original_html, target_origin_url)
        known_sources = {
            str(node.get("src", ""))
            for node in [
                *original_script_nodes,
                *live_script_nodes,
                *runtime_script_nodes,
            ]
        }
        resource_nodes = [
            {"src": str(source_url), "text": ""}
            for source_url in loaded_script_urls
            if str(source_url) and str(source_url) not in known_sources
        ]
        script_nodes = merge_script_nodes(
            original_script_nodes,
            live_script_nodes,
            runtime_script_nodes,
            resource_nodes,
        )

        chunks: list[str] = []
        warnings: list[str] = []
        scripts_found = len(script_nodes)
        current_bytes = 0
        fetched_sources: set[str] = set()

        for node in script_nodes:
            inline_text = str(node.get("text", ""))
            source_url = str(node.get("src", ""))

            if inline_text:
                remaining = self.settings.max_script_bytes - current_bytes
                if remaining <= 0:
                    warnings.append("inline JavaScript truncated by MAX_SCRIPT_BYTES")
                    break
                encoded = inline_text.encode("utf-8", errors="ignore")
                bounded = encoded[:remaining]
                chunks.append(bounded.decode("utf-8", errors="ignore"))
                current_bytes += len(bounded)
                if len(encoded) > remaining:
                    warnings.append("inline JavaScript truncated by MAX_SCRIPT_BYTES")
                    break
                continue

            if not source_url or source_url in fetched_sources:
                continue
            fetched_sources.add(source_url)
            try:
                is_same_origin = same_origin(target_origin_url, source_url)
            except ValueError:
                warnings.append("script URL was invalid and was skipped")
                continue
            if not self.settings.include_third_party_scripts and not is_same_origin:
                continue

            try:
                validated_source = await self.policy.validate(source_url)
                response = await context.request.get(
                    validated_source,
                    timeout=self.settings.request_timeout_seconds * 1000,
                    fail_on_status_code=False,
                )
                if not response.ok:
                    warnings.append(
                        "script fetch returned "
                        f"HTTP {response.status}: {redact_url_query(validated_source)}"
                    )
                    continue
                final_source = await self.policy.validate(response.url)
                if not self.settings.include_third_party_scripts and not same_origin(
                    target_origin_url, final_source
                ):
                    warnings.append("script redirect left the target origin and was skipped")
                    continue
                remaining = self.settings.max_script_bytes - current_bytes
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > remaining:
                    warnings.append(
                        "external JavaScript skipped because it exceeded MAX_SCRIPT_BYTES"
                    )
                    continue
                body = await response.body()
                if remaining <= 0:
                    warnings.append("external JavaScript truncated by MAX_SCRIPT_BYTES")
                    break
                body = body[:remaining]
                chunks.append(body.decode("utf-8", errors="replace"))
                current_bytes += len(body)
            except Exception as exc:
                warnings.append(f"script fetch failed: {type(exc).__name__}")

        return "\n".join(chunks), scripts_found, warnings

    async def _start_runtime_script_collection(
        self,
        context: BrowserContext,
        page: Page,
    ) -> tuple[CDPSession, list[dict[str, object]]]:
        """Track JavaScript parsed by Chromium, including eval/new Function sources."""
        session = await context.new_cdp_session(page)
        try:
            parsed_scripts: list[dict[str, object]] = []

            def record_script(event: object) -> None:
                if isinstance(event, dict):
                    parsed_scripts.append(event)

            session.on("Debugger.scriptParsed", record_script)
            await session.send("Debugger.enable")
            # Enabling the debugger replays scripts from the document that is
            # about to be replaced. Keep only scripts parsed for this navigation.
            await asyncio.sleep(0)
            parsed_scripts.clear()
            return session, parsed_scripts
        except Exception:
            await self._safe_detach_cdp_session(session)
            raise

    @staticmethod
    async def _safe_detach_cdp_session(session: CDPSession) -> None:
        try:
            await session.detach()
        except Exception:
            logger.debug("CDP session cleanup failed", exc_info=True)

    async def _finish_runtime_script_collection(
        self,
        session: CDPSession,
        parsed_scripts: list[dict[str, object]],
    ) -> tuple[list[dict[str, str]], list[str]]:
        nodes: list[dict[str, str]] = []
        warnings: list[str] = []
        seen_ids: set[str] = set()
        failures = 0

        for event in parsed_scripts:
            if not isinstance(event, dict):
                failures += 1
                continue
            script_id = str(event.get("scriptId", ""))
            if not script_id or script_id in seen_ids:
                continue
            seen_ids.add(script_id)
            try:
                result = await session.send(
                    "Debugger.getScriptSource",
                    {"scriptId": script_id},
                )
            except Exception:
                failures += 1
                continue

            if not isinstance(result, dict):
                failures += 1
                continue
            source = str(result.get("scriptSource", "")).strip()
            if not source:
                continue
            nodes.append({"src": str(event.get("url", "")), "text": source})

        if failures:
            warnings.append(
                f"Chromium runtime source could not be read ({failures} occurrences)"
            )
        return nodes, warnings

    async def _collect_page(
        self,
        context: BrowserContext,
        page: Page,
        url: str,
        target_origin_url: str,
    ) -> tuple[PageArtifact, list[str]]:
        warnings: list[str] = []
        cdp_session: CDPSession | None = None
        parsed_scripts: list[dict[str, object]] = []
        try:
            cdp_session, parsed_scripts = await self._start_runtime_script_collection(
                context,
                page,
            )
        except Exception as exc:
            warnings.append(
                f"Chromium runtime source collection unavailable: {type(exc).__name__}"
            )

        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.settings.request_timeout_seconds * 1000,
            )
        except Exception:
            if cdp_session is not None:
                await self._safe_detach_cdp_session(cdp_session)
            raise
        if response is not None and response.status >= 400:
            warnings.append(f"page returned HTTP {response.status}")

        original_html = ""
        if response is not None:
            try:
                original_html = await response.text()
                original_bytes = original_html.encode("utf-8", errors="ignore")
                if len(original_bytes) > self.settings.max_page_bytes:
                    original_html = original_bytes[: self.settings.max_page_bytes].decode(
                        "utf-8", errors="replace"
                    )
                    warnings.append("original HTML truncated by MAX_PAGE_BYTES")
            except Exception as exc:
                warnings.append(f"original HTML could not be read: {type(exc).__name__}")

        try:
            await page.wait_for_load_state(
                "networkidle",
                timeout=min(self.settings.request_timeout_seconds, 5) * 1000,
            )
        except Exception:
            warnings.append(_NETWORK_IDLE_WARNING)

        runtime_script_nodes: list[dict[str, str]] = []
        if cdp_session is not None:
            try:
                runtime_script_nodes, runtime_warnings = (
                    await self._finish_runtime_script_collection(
                        cdp_session,
                        parsed_scripts,
                    )
                )
                warnings.extend(runtime_warnings)
            except Exception as exc:
                warnings.append(
                    f"Chromium runtime source collection failed: {type(exc).__name__}"
                )
            finally:
                await self._safe_detach_cdp_session(cdp_session)

        final_url = await self.policy.validate(page.url)
        if not same_origin(target_origin_url, final_url):
            raise UnsafeTargetError("page redirect left the target origin")
        rendered_dom = await page.content()
        raw_dom = rendered_dom.encode("utf-8", errors="ignore")
        if len(raw_dom) > self.settings.max_page_bytes:
            rendered_dom = raw_dom[: self.settings.max_page_bytes].decode("utf-8", errors="replace")
            warnings.append("rendered DOM truncated by MAX_PAGE_BYTES")

        javascript, scripts_found, script_warnings = await self._extract_scripts(
            context,
            page,
            final_url,
            original_html,
            runtime_script_nodes,
        )
        warnings.extend(script_warnings)

        hrefs = await page.locator("a[href]").evaluate_all("nodes => nodes.map(node => node.href)")
        links = [
            canonical
            for href in hrefs
            if (canonical := canonicalize_link(final_url, str(href))) is not None
        ]

        artifact = PageArtifact(
            url=final_url,
            title=await page.title(),
            rendered_dom=rendered_dom,
            javascript=javascript,
            links_found=len(links),
            scripts_found=scripts_found,
            warnings=warnings,
        )
        return artifact, links

    async def crawl(self, target_url: str, scope_mode: str) -> list[PageArtifact]:
        validated_target = await self.policy.validate(target_url)
        max_pages = 1 if scope_mode == "page" else self.settings.max_pages

        queue: deque[tuple[str, int]] = deque([(validated_target, 0)])
        queued: set[str] = {validated_target}
        visited: set[str] = set()
        results: list[PageArtifact] = []

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--disable-extensions",
                    "--disable-sync",
                    "--metrics-recording-only",
                    "--no-first-run",
                ],
            )
            context = await browser.new_context(
                user_agent=self.settings.user_agent,
                ignore_https_errors=False,
                java_script_enabled=True,
            )
            await context.route("**/*", self._route_guard)
            page = await context.new_page()

            try:
                while queue and len(results) < max_pages:
                    current_url, depth = queue.popleft()
                    if current_url in visited:
                        continue
                    visited.add(current_url)

                    try:
                        artifact, discovered_links = await self._collect_page(
                            context,
                            page,
                            current_url,
                            validated_target,
                        )
                        results.append(artifact)
                    except Exception as exc:
                        logger.exception(
                            "page collection failed",
                            extra={
                                "target_host": urlsplit(current_url).hostname or "",
                                "error_type": type(exc).__name__,
                            },
                        )
                        results.append(
                            PageArtifact(
                                url=current_url,
                                title="",
                                rendered_dom="",
                                javascript="",
                                links_found=0,
                                scripts_found=0,
                                warnings=[f"page collection failed: {type(exc).__name__}"],
                            )
                        )
                        continue

                    if scope_mode == "page" or depth >= self.settings.max_crawl_depth:
                        continue

                    for link in discovered_links:
                        if link in queued or link in visited:
                            continue
                        if not same_origin(validated_target, link):
                            continue
                        if not is_safe_crawl_link(link):
                            continue
                        queued.add(link)
                        queue.append((link, depth + 1))

                    if self.settings.crawl_delay_ms:
                        await asyncio.sleep(self.settings.crawl_delay_ms / 1000)
            finally:
                await context.close()
                await browser.close()

        return results
