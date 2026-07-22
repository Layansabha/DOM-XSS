from __future__ import annotations

import asyncio
import re
from collections import Counter, deque
from dataclasses import asdict, dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from playwright.async_api import BrowserContext, Page, Route, async_playwright

from app.config import Settings
from app.services.url_guard import RequestPolicy, UnsafeTargetError, same_origin

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
    if _NETWORK_IDLE_WARNING in warnings:
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
    ) -> tuple[str, int, list[str]]:
        script_nodes = await page.locator("script").evaluate_all(
            """nodes => nodes.map(node => ({
                src: node.src || "",
                text: node.src ? "" : (node.textContent || "")
            }))"""
        )
        loaded_script_urls = await page.evaluate(
            """() => performance.getEntriesByType('resource')
                .filter(entry => entry.initiatorType === 'script')
                .map(entry => entry.name)"""
        )
        known_sources = {str(node.get("src", "")) for node in script_nodes}
        script_nodes.extend(
            {"src": str(source_url), "text": ""}
            for source_url in loaded_script_urls
            if str(source_url) and str(source_url) not in known_sources
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
                        f"script fetch returned HTTP {response.status}: {validated_source}"
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

    async def _collect_page(
        self,
        context: BrowserContext,
        page: Page,
        url: str,
        target_origin_url: str,
    ) -> tuple[PageArtifact, list[str]]:
        warnings: list[str] = []
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=self.settings.request_timeout_seconds * 1000,
        )
        if response is not None and response.status >= 400:
            warnings.append(f"page returned HTTP {response.status}")

        try:
            await page.wait_for_load_state(
                "networkidle",
                timeout=min(self.settings.request_timeout_seconds, 5) * 1000,
            )
        except Exception:
            warnings.append(_NETWORK_IDLE_WARNING)

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
                        results.append(
                            PageArtifact(
                                url=current_url,
                                title="",
                                rendered_dom="",
                                javascript="",
                                links_found=0,
                                scripts_found=0,
                                warnings=[f"page collection failed: {type(exc).__name__}: {exc}"],
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
