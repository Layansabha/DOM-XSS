from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit

from app.config import Settings


class UnsafeTargetError(ValueError):
    pass


def normalize_url(raw_url: str) -> str:
    value = raw_url.strip()
    if not value:
        raise UnsafeTargetError("target URL is empty")

    if "://" not in value:
        value = f"https://{value}"

    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeTargetError("only http and https targets are supported")
    if not parsed.hostname:
        raise UnsafeTargetError("target URL must include a hostname")
    if parsed.username or parsed.password:
        raise UnsafeTargetError("credentials in target URLs are not allowed")

    hostname = parsed.hostname.encode("idna").decode("ascii").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        raise UnsafeTargetError("localhost targets are blocked")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeTargetError("target URL has an invalid port") from exc
    netloc = hostname if port is None else f"{hostname}:{port}"

    path = parsed.path or "/"
    normalized = SplitResult(
        scheme=parsed.scheme.lower(),
        netloc=netloc,
        path=path,
        query=parsed.query,
        fragment="",
    )
    return urlunsplit(normalized)


def infer_scope_mode(url: str) -> str:
    parsed = urlsplit(url)
    is_root = parsed.path in {"", "/"} and not parsed.query
    return "domain" if is_root else "page"


def origin_tuple(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    if not parsed.hostname:
        raise UnsafeTargetError("URL has no hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme, parsed.hostname.lower(), port


def same_origin(left: str, right: str) -> bool:
    return origin_tuple(left) == origin_tuple(right)


def _is_blocked_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


async def resolve_host(
    hostname: str,
    port: int,
) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    def _resolve() -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        records = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        return {ipaddress.ip_address(record[4][0]) for record in records}

    try:
        return await asyncio.to_thread(_resolve)
    except socket.gaierror as exc:
        raise UnsafeTargetError(f"DNS resolution failed for {hostname}") from exc


@dataclass
class RequestPolicy:
    settings: Settings

    async def validate(self, raw_url: str) -> str:
        normalized = normalize_url(raw_url)
        parsed = urlsplit(normalized)
        assert parsed.hostname is not None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        # Resolve on every request. Caching an allow decision makes DNS rebinding easier.
        addresses = await resolve_host(parsed.hostname, port)
        if not addresses:
            raise UnsafeTargetError("target hostname resolved to no addresses")
        if not self.settings.allow_private_targets and any(
            _is_blocked_ip(address) for address in addresses
        ):
            raise UnsafeTargetError(
                "private, loopback, link-local, reserved, or multicast targets are blocked"
            )

        return normalized
