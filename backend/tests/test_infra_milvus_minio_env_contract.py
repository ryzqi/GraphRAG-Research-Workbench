from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def test_infra_uses_single_compose_source() -> None:
    canonical_compose_path = REPO_ROOT / "infra/podman-compose.yml"

    assert canonical_compose_path.exists()

    removed_paths = (
        "infra/podman-compose.base.yml",
        "infra/podman-compose.dev.yml",
        "infra/podman-compose.prod.example.yml",
    )
    for relative_path in removed_paths:
        assert not (REPO_ROOT / relative_path).exists(), relative_path


def test_milvus_service_uses_supported_minio_env_names() -> None:
    compose_path = REPO_ROOT / "infra/podman-compose.yml"
    payload = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    milvus_env = payload["services"]["milvus"]["environment"]

    assert milvus_env["MINIO_ACCESS_KEY_ID"] == "${MINIO_ROOT_USER}"
    assert milvus_env["MINIO_SECRET_ACCESS_KEY"] == "${MINIO_ROOT_PASSWORD}"
    assert "MINIO_ACCESS_KEY" not in milvus_env
    assert "MINIO_SECRET_KEY" not in milvus_env


def test_root_env_example_points_to_compose_service_hosts() -> None:
    env_values = _load_dotenv(REPO_ROOT / ".env.example")

    assert env_values["CORE__DATABASE_URL"] == (
        "postgresql+asyncpg://<db-user>:<db-password>@postgres:5432/<db-name>"
    )
    assert env_values["CORE__REDIS_URL"] == "redis://redis:6379/0"
    assert env_values["CORE__CELERY_BROKER_URL"] == "redis://redis:6379/0"
    assert env_values["CORE__CELERY_RESULT_BACKEND"] == "redis://redis:6379/1"
    assert env_values["STORAGE__MINIO_ENDPOINT"] == "minio:9000"
    assert env_values["MILVUS_HOST"] == "milvus"
    assert env_values["MILVUS_PORT"] == "19530"
    assert env_values["WEB_SEARCH__SEARXNG_SEARCH_BASE_URL"] == "http://searxng:8080"
