from __future__ import annotations

import ipaddress

import pytest

from app.config import Settings
from app.services.url_guard import (
    RequestPolicy,
    UnsafeTargetError,
    infer_scope_mode,
    normalize_url,
    same_origin,
)


def test_normalize_url_adds_https_and_root_path() -> None:
    assert normalize_url("Example.COM") == "https://example.com/"


def test_normalize_url_rejects_credentials() -> None:
    with pytest.raises(UnsafeTargetError):
        normalize_url("https://user:pass@example.com/")


def test_normalize_url_preserves_ipv6_brackets_and_port() -> None:
    assert (
        normalize_url("https://[2606:4700:4700::1111]:8443/path")
        == "https://[2606:4700:4700::1111]:8443/path"
    )


def test_normalize_url_rejects_malformed_ipv6() -> None:
    with pytest.raises(UnsafeTargetError, match="malformed"):
        normalize_url("https://[2606:4700::1111/path")


def test_infer_scope_mode() -> None:
    assert infer_scope_mode("https://example.com/") == "domain"
    assert infer_scope_mode("https://example.com/app") == "page"
    assert infer_scope_mode("https://example.com/?q=1") == "page"


def test_same_origin_respects_scheme_host_and_port() -> None:
    assert same_origin("https://example.com/a", "https://example.com/b")
    assert not same_origin("https://example.com", "http://example.com")
    assert not same_origin("https://example.com", "https://sub.example.com")


@pytest.mark.asyncio
async def test_policy_blocks_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(hostname: str, port: int) -> set[object]:
        return {ipaddress.ip_address("127.0.0.1")}

    monkeypatch.setattr("app.services.url_guard.resolve_host", fake_resolve)
    policy = RequestPolicy(Settings(allow_private_targets=False))

    with pytest.raises(UnsafeTargetError):
        await policy.validate("http://localhost/")


@pytest.mark.asyncio
async def test_policy_can_allow_private_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(hostname: str, port: int) -> set[object]:
        return {ipaddress.ip_address("10.0.0.5")}

    monkeypatch.setattr("app.services.url_guard.resolve_host", fake_resolve)
    policy = RequestPolicy(Settings(allow_private_targets=True))

    assert await policy.validate("http://internal.test/") == "http://internal.test/"


@pytest.mark.asyncio
async def test_policy_rechecks_dns_and_blocks_changed_private_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter(
        [
            {ipaddress.ip_address("93.184.216.34")},
            {ipaddress.ip_address("10.0.0.5")},
        ]
    )

    async def fake_resolve(hostname: str, port: int) -> set[object]:
        return next(answers)

    monkeypatch.setattr("app.services.url_guard.resolve_host", fake_resolve)
    policy = RequestPolicy(Settings(allow_private_targets=False))

    assert await policy.validate("https://example.test/") == "https://example.test/"
    with pytest.raises(UnsafeTargetError):
        await policy.validate("https://example.test/redirect")
