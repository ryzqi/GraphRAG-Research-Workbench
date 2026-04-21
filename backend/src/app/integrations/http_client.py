from __future__ import annotations

from enum import StrEnum

import httpx

from app.core.settings import Settings, get_settings


class HttpClientProfile(StrEnum):
    DEFAULT = "default"
    EMBEDDING_REALTIME = "embedding_realtime"
    EMBEDDING_BATCH = "embedding_batch"


def _normalize_profile(profile: HttpClientProfile | str) -> HttpClientProfile:
    if isinstance(profile, HttpClientProfile):
        return profile
    raw = str(profile or HttpClientProfile.DEFAULT).strip().lower()
    try:
        return HttpClientProfile(raw)
    except ValueError:
        return HttpClientProfile.DEFAULT


def _profile_setting(
    settings: Settings,
    *,
    profile: HttpClientProfile,
    suffix: str,
):
    if profile == HttpClientProfile.DEFAULT:
        return getattr(settings, f"http_{suffix}")
    prefix = (
        "embedding_http_realtime"
        if profile == HttpClientProfile.EMBEDDING_REALTIME
        else "embedding_http_batch"
    )
    override = getattr(settings, f"{prefix}_{suffix}", None)
    if override is None:
        return getattr(settings, f"http_{suffix}")
    return override


def _build_timeout(
    settings: Settings,
    *,
    profile: HttpClientProfile = HttpClientProfile.DEFAULT,
) -> httpx.Timeout:
    return httpx.Timeout(
        connect=float(
            _profile_setting(
                settings,
                profile=profile,
                suffix="timeout_connect_seconds",
            )
        ),
        read=float(
            _profile_setting(
                settings,
                profile=profile,
                suffix="timeout_read_seconds",
            )
        ),
        write=float(
            _profile_setting(
                settings,
                profile=profile,
                suffix="timeout_write_seconds",
            )
        ),
        pool=float(
            _profile_setting(
                settings,
                profile=profile,
                suffix="timeout_pool_seconds",
            )
        ),
    )


def _build_limits(
    settings: Settings,
    *,
    profile: HttpClientProfile = HttpClientProfile.DEFAULT,
) -> httpx.Limits:
    return httpx.Limits(
        max_connections=int(
            _profile_setting(settings, profile=profile, suffix="max_connections")
        ),
        max_keepalive_connections=int(
            _profile_setting(
                settings,
                profile=profile,
                suffix="max_keepalive_connections",
            )
        ),
        keepalive_expiry=float(
            _profile_setting(
                settings,
                profile=profile,
                suffix="keepalive_expiry_seconds",
            )
        ),
    )


def create_http_client(
    settings: Settings | None = None,
    *,
    profile: HttpClientProfile | str = HttpClientProfile.DEFAULT,
) -> httpx.AsyncClient:
    cfg = settings or get_settings()
    normalized_profile = _normalize_profile(profile)
    return httpx.AsyncClient(
        trust_env=False,
        timeout=_build_timeout(cfg, profile=normalized_profile),
        limits=_build_limits(cfg, profile=normalized_profile),
    )


async def close_http_client(client: httpx.AsyncClient | None) -> None:
    """关闭 httpx 客户端（尽力而为）。"""
    if client is None:
        return
    try:
        await client.aclose()
    except Exception:  # pragma: no cover - best effort
        return
