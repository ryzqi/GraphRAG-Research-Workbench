from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from app.core.errors import AppError
from app.core.settings import Settings, get_settings
from app.services.ingestion_batch_service_contracts import (
    _BlockedCidrRule,
    _DEFAULT_URL_REDIRECTS,
    _DEFAULT_URL_TIMEOUT_SECONDS,
    _FALLBACK_BLOCKED_CIDRS_V4,
    _FALLBACK_BLOCKED_CIDRS_V6,
    _FALLBACK_METADATA_BLOCKED_IPS,
)
from app.services.ingestion_contract import ingestion_error

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class UrlIngestionGuard:
    settings: Settings
    blocked_cidr_rules: tuple[_BlockedCidrRule, ...]
    metadata_blocked_ips: frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address]

    def canonicalize_url(self, url: str) -> str:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path or "/"
        return urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))

    async def validate_source_url(
        self,
        url: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> str:
        canonical_url = self.canonicalize_url(url)
        self._ensure_http_scheme(canonical_url, original_url=url)

        if client is not None:
            return await self._validate_url_security(canonical_url, client=client)

        timeout_seconds = max(
            float(
                getattr(
                    self.settings,
                    "ingestion_url_timeout_seconds",
                    _DEFAULT_URL_TIMEOUT_SECONDS,
                )
            ),
            1.0,
        )
        async with httpx.AsyncClient(timeout=timeout_seconds) as owned_client:
            return await self._validate_url_security(canonical_url, client=owned_client)

    async def validate_navigation_url(self, url: str) -> str:
        canonical_url = self.canonicalize_url(url)
        self._ensure_http_scheme(canonical_url, original_url=url)
        parsed = urlparse(canonical_url)
        host = parsed.hostname
        if not host:
            raise ingestion_error("URL_SCHEME_NOT_ALLOWED", details={"url": url})
        await self._assert_host_safe(host, current_url=canonical_url, redirect_hop=0)
        return canonical_url

    def _ensure_http_scheme(self, url: str, *, original_url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ingestion_error(
                "URL_SCHEME_NOT_ALLOWED",
                details={"url": original_url},
            )

    async def _validate_url_security(
        self,
        url: str,
        *,
        client: httpx.AsyncClient,
    ) -> str:
        current = url
        max_redirects = max(
            int(
                getattr(
                    self.settings,
                    "ingestion_url_max_redirects",
                    _DEFAULT_URL_REDIRECTS,
                )
            ),
            0,
        )
        for redirect_hops in range(max_redirects + 1):
            parsed = urlparse(current)
            host = parsed.hostname
            if not host:
                raise ingestion_error(
                    "URL_SCHEME_NOT_ALLOWED",
                    details={"url": current},
                )

            await self._assert_host_safe(
                host,
                current_url=current,
                redirect_hop=redirect_hops,
            )

            if redirect_hops == max_redirects:
                break

            try:
                response = await client.get(current, follow_redirects=False)
            except Exception as exc:
                raise ingestion_error(
                    "URL_SSRF_BLOCKED",
                    message="URL 安全探测失败",
                    details={"url": current, "reason": str(exc), "retryable": True},
                ) from exc

            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    break
                current = self.canonicalize_url(urljoin(current, location))
                continue
            break

        return current

    async def _assert_host_safe(
        self,
        host: str,
        *,
        current_url: str,
        redirect_hop: int,
    ) -> None:
        try:
            ips = [ipaddress.ip_address(host)]
        except ValueError:
            ips = await asyncio.to_thread(_resolve_host_ips, host)

        resolved_ips = [str(ip) for ip in ips]
        if not ips:
            raise ingestion_error(
                "URL_SSRF_BLOCKED",
                details={
                    "host": host,
                    "url": current_url,
                    "redirect_hop": redirect_hop,
                    "resolved_ips": [],
                    "blocked_ips": [],
                    "blocked_reason": "unresolvable",
                },
            )

        blocked: list[tuple[str, str]] = []
        for ip in ips:
            reason = _blocked_reason_for_ip(
                ip,
                blocked_cidr_rules=self.blocked_cidr_rules,
                metadata_blocked_ips=self.metadata_blocked_ips,
            )
            if reason:
                blocked.append((str(ip), reason))

        if blocked:
            blocked_ips = [ip for ip, _ in blocked]
            blocked_reasons = sorted({reason for _, reason in blocked})
            raise ingestion_error(
                "URL_SSRF_BLOCKED",
                details={
                    "host": host,
                    "url": current_url,
                    "redirect_hop": redirect_hop,
                    "resolved_ips": resolved_ips,
                    "blocked_ips": blocked_ips,
                    "blocked_reason": blocked_reasons[0]
                    if len(blocked_reasons) == 1
                    else "multiple",
                    "blocked_reasons": blocked_reasons,
                },
            )


def build_url_ingestion_guard(
    settings: Settings | None = None,
) -> UrlIngestionGuard:
    cfg = settings or get_settings()
    return UrlIngestionGuard(
        settings=cfg,
        blocked_cidr_rules=_build_blocked_cidr_rules(cfg),
        metadata_blocked_ips=_build_metadata_blocked_ips(cfg),
    )


def _build_blocked_cidr_rules(settings: Settings) -> tuple[_BlockedCidrRule, ...]:
    rules: list[_BlockedCidrRule] = []
    configured_v4 = [raw for raw in getattr(settings, "ingestion_url_blocked_cidrs_v4", [])]
    configured_v6 = [raw for raw in getattr(settings, "ingestion_url_blocked_cidrs_v6", [])]

    if not configured_v4 and not configured_v6:
        configured_v4 = list(_FALLBACK_BLOCKED_CIDRS_V4)
        configured_v6 = list(_FALLBACK_BLOCKED_CIDRS_V6)

    configured: list[tuple[str, str]] = [
        (raw, "private_or_local_cidr") for raw in configured_v4
    ]
    configured.extend((raw, "private_or_local_cidr") for raw in configured_v6)
    for raw, reason in configured:
        text = raw.strip()
        if not text:
            continue
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError:
            logger.warning("Ignore invalid ingestion URL blocked CIDR: %s", text)
            continue
        rules.append(_BlockedCidrRule(network=network, reason=reason))

    if not rules:
        logger.warning(
            "No valid ingestion URL blocked CIDRs configured; fallback to safe defaults"
        )
        for raw in [*_FALLBACK_BLOCKED_CIDRS_V4, *_FALLBACK_BLOCKED_CIDRS_V6]:
            network = ipaddress.ip_network(raw, strict=False)
            rules.append(
                _BlockedCidrRule(network=network, reason="private_or_local_cidr")
            )
    return tuple(rules)


def _build_metadata_blocked_ips(
    settings: Settings,
) -> frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    blocked_ips: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    configured = list(getattr(settings, "ingestion_url_metadata_blocklist", []))
    if not configured:
        configured = list(_FALLBACK_METADATA_BLOCKED_IPS)
    for raw in configured:
        text = raw.strip()
        if not text:
            continue
        try:
            blocked_ips.add(ipaddress.ip_address(text))
        except ValueError:
            logger.warning("Ignore invalid ingestion URL metadata blocked IP: %s", text)

    if not blocked_ips:
        logger.warning(
            "No valid ingestion URL metadata blocked IP configured; fallback to safe defaults"
        )
        blocked_ips = {
            ipaddress.ip_address(raw) for raw in _FALLBACK_METADATA_BLOCKED_IPS
        }
    return frozenset(blocked_ips)


def _blocked_reason_for_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    blocked_cidr_rules: tuple[_BlockedCidrRule, ...],
    metadata_blocked_ips: frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address],
) -> str | None:
    if ip in metadata_blocked_ips:
        return "metadata_ip"

    for rule in blocked_cidr_rules:
        if ip.version != rule.network.version:
            continue
        if ip in rule.network:
            return rule.reason

    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link_local"
    if ip.is_multicast:
        return "multicast"
    if ip.is_unspecified:
        return "unspecified"
    return None


def _resolve_host_ips(
    host: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in socket.getaddrinfo(host, None):
        raw = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(raw))
        except ValueError:
            continue
    uniq = {str(ip): ip for ip in addresses}
    return list(uniq.values())


def normalize_url_guard_error(
    exc: AppError,
    *,
    error_code: str,
    message: str,
    url: str,
) -> AppError:
    details = dict(exc.details or {})
    details.setdefault("url", url)
    details.setdefault("reason_code", exc.code)
    return AppError(
        code=error_code,
        message=message,
        status_code=exc.status_code,
        details=details or None,
    )
