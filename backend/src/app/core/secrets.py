"""敏感字段加密/脱敏工具。"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.settings import Settings, get_settings

_DEV_FALLBACK_MODEL_CONFIG_KMS_KEY = "dev-model-config-kms-key"
_DEV_ENVS = {"dev", "development", "local", "test"}


def resolve_model_config_kms_key(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    raw = (cfg.model_config_kms_key or "").strip()
    if raw:
        return raw
    if cfg.app_env.strip().lower() in _DEV_ENVS:
        return _DEV_FALLBACK_MODEL_CONFIG_KMS_KEY
    raise RuntimeError("MODEL_CONFIG_KMS_KEY is required in non-dev environments")


def _build_fernet(raw_key: str) -> Fernet:
    digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str, *, kms_key: str) -> str:
    value = plaintext.strip()
    if not value:
        return ""
    return _build_fernet(kms_key).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str, *, kms_key: str) -> str:
    token = ciphertext.strip()
    if not token:
        return ""
    try:
        plain = _build_fernet(kms_key).decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("invalid encrypted secret payload") from exc
    return plain.decode("utf-8")


def mask_secret(secret: str | None) -> str | None:
    if secret is None:
        return None
    value = secret.strip()
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 6)}{value[-2:]}"
