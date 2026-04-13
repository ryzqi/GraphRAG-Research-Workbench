from __future__ import annotations

import json
import sys
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from app.config.app_env import AppEnv

IPV4_LOOPBACK = "127.0.0.1"
LOOPBACK_HOSTS = {"localhost", IPV4_LOOPBACK, "::1"}

DEV_LOCAL_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

LEGACY_VITE_LOCAL_CORS_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}

DEFAULT_INGESTION_BLOCKED_CIDRS_V4 = [
    "0.0.0.0/8",
    "10.0.0.0/8",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
]

DEFAULT_INGESTION_BLOCKED_CIDRS_V6 = [
    "::/128",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]

DEFAULT_INGESTION_METADATA_BLOCKLIST = [
    "169.254.169.254",
]

DEV_DEFAULT_DATABASE_URL = "postgresql+asyncpg://mkb:mkb_password@localhost:5432/mkb"
DEV_DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEV_DEFAULT_CELERY_BROKER_URL = "redis://localhost:6379/0"
DEV_DEFAULT_CELERY_RESULT_BACKEND = "redis://localhost:6379/1"
DEV_DEFAULT_MINIO_ACCESS_KEY = "minioadmin"
DEV_DEFAULT_MINIO_SECRET_KEY = "minioadmin"
PLACEHOLDER_SECRET_VALUES = {"", "REPLACE_ME", "CHANGE_ME", "change-me", "minioadmin"}


def dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def parse_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return dedupe_keep_order([str(item) for item in value])
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            else:
                if isinstance(parsed, list):
                    return dedupe_keep_order([str(item) for item in parsed])
        parts = [part.strip().strip('"').strip("'") for part in raw.split(",")]
        return dedupe_keep_order(parts)
    return dedupe_keep_order([str(value)])


def prefer_ipv4_loopback_url(value: str) -> str:
    if not value or not sys.platform.startswith("win"):
        return value

    try:
        parts = urlsplit(value)
    except Exception:
        return value

    if parts.hostname != "localhost":
        return value

    userinfo = ""
    if parts.username is not None:
        userinfo = quote(parts.username, safe="")
        if parts.password is not None:
            userinfo += ":" + quote(parts.password, safe="")
        userinfo += "@"

    port = f":{parts.port}" if parts.port else ""
    netloc = f"{userinfo}{IPV4_LOOPBACK}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def prefer_ipv4_loopback_hostport(value: str) -> str:
    if not value or not sys.platform.startswith("win"):
        return value

    raw = value.strip()
    if not raw:
        return value

    if raw == "localhost":
        return IPV4_LOOPBACK
    if raw.startswith("localhost:"):
        return IPV4_LOOPBACK + raw[len("localhost") :]
    return value


def normalize_url_for_compare(value: str) -> str:
    return prefer_ipv4_loopback_url(value.strip())


def is_development_like_env(app_env: AppEnv | str | None) -> bool:
    return AppEnv.from_value(app_env).is_development_like


def parse_origins(value: object) -> list[str]:
    if value is None:
        return DEV_LOCAL_CORS_ORIGINS.copy()
    return parse_string_list(value)


def ensure_local_dev_cors_origins(app_env: AppEnv | str, origins: list[str]) -> list[str]:
    if not is_development_like_env(app_env):
        return origins

    custom_origins = [
        origin for origin in origins if origin not in LEGACY_VITE_LOCAL_CORS_ORIGINS
    ]
    return dedupe_keep_order([*custom_origins, *DEV_LOCAL_CORS_ORIGINS])


def contains_loopback_url(value: str) -> bool:
    raw = normalize_url_for_compare(value)
    try:
        hostname = urlsplit(raw).hostname
    except Exception:
        return False
    return (hostname or "").strip().lower() in LOOPBACK_HOSTS


def contains_loopback_hostport(value: str) -> bool:
    raw = prefer_ipv4_loopback_hostport(value).strip()
    if not raw:
        return False

    if raw.startswith("[") and "]" in raw:
        host = raw[1 : raw.index("]")]
    else:
        host = raw.split(":", 1)[0]
    return host.strip().lower() in LOOPBACK_HOSTS


def _is_blank_or_placeholder(value: object) -> bool:
    normalized = str(value or "").strip()
    return normalized in PLACEHOLDER_SECRET_VALUES


def validate_startup_settings(settings: Any) -> None:
    if is_development_like_env(getattr(settings, "app_env", None)):
        return

    problems: list[str] = []

    database_url = str(getattr(settings, "database_url", "") or "").strip()
    if not database_url:
        problems.append("DATABASE_URL 为空")
    elif contains_loopback_url(database_url):
        problems.append("DATABASE_URL 指向 loopback 地址")

    redis_url = str(getattr(settings, "redis_url", "") or "").strip()
    if not redis_url:
        problems.append("REDIS_URL 为空")
    elif contains_loopback_url(redis_url):
        problems.append("REDIS_URL 指向 loopback 地址")

    celery_broker_url = str(getattr(settings, "celery_broker_url", "") or "").strip()
    if not celery_broker_url:
        problems.append("CELERY_BROKER_URL 为空")
    elif contains_loopback_url(celery_broker_url):
        problems.append("CELERY_BROKER_URL 指向 loopback 地址")

    celery_result_backend = str(
        getattr(settings, "celery_result_backend", "") or ""
    ).strip()
    if not celery_result_backend:
        problems.append("CELERY_RESULT_BACKEND 为空")
    elif contains_loopback_url(celery_result_backend):
        problems.append("CELERY_RESULT_BACKEND 指向 loopback 地址")

    embedding_api_key = str(getattr(settings, "embedding_api_key", "") or "").strip()
    if _is_blank_or_placeholder(embedding_api_key):
        problems.append("EMBEDDING_API_KEY 为空或为占位值")

    model_config_kms_key = str(
        getattr(settings, "model_config_kms_key", "") or ""
    ).strip()
    if not model_config_kms_key:
        problems.append("MODEL_CONFIG_KMS_KEY 为空")

    minio_endpoint = str(getattr(settings, "minio_endpoint", "") or "").strip()
    if not minio_endpoint:
        problems.append("MINIO_ENDPOINT 为空")
    elif contains_loopback_hostport(minio_endpoint):
        problems.append("MINIO_ENDPOINT 指向 loopback 地址")

    if _is_blank_or_placeholder(getattr(settings, "minio_access_key", "")):
        problems.append("MINIO_ACCESS_KEY 为空或为默认值")

    if _is_blank_or_placeholder(getattr(settings, "minio_secret_key", "")):
        problems.append("MINIO_SECRET_KEY 为空或为默认值")

    searxng_enabled = bool(getattr(settings, "searxng_search_enabled", False))
    searxng_base_url = str(
        getattr(settings, "searxng_search_base_url", "") or ""
    ).strip()
    if searxng_enabled and not searxng_base_url:
        problems.append("SEARXNG_BASE_URL 为空")
    elif searxng_enabled and contains_loopback_url(searxng_base_url):
        problems.append("SEARXNG_BASE_URL 指向 loopback 地址")

    tavily_enabled = bool(str(getattr(settings, "web_search_api_key", "") or "").strip())
    tavily_base_url = str(getattr(settings, "tavily_base_url", "") or "").strip()
    if tavily_enabled and not tavily_base_url:
        problems.append("TAVILY_BASE_URL 为空")
    elif tavily_enabled and contains_loopback_url(tavily_base_url):
        problems.append("TAVILY_BASE_URL 指向 loopback 地址")

    if problems:
        app_env = AppEnv.from_value(getattr(settings, "app_env", None))
        raise RuntimeError(
            f"启动安全校验失败（APP_ENV={app_env.value}）：{'; '.join(problems)}"
        )
