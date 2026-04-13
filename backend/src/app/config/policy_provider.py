from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import yaml


class PolicyProvider(Protocol):
    def load_policy_data(self, policy_name: str) -> dict[str, Any]: ...


class StaticFilePolicyProvider:
    def __init__(self, *, base_path: Path | None = None) -> None:
        self._base_path = (
            base_path
            if base_path is not None
            else Path(__file__).resolve().parent / "policies"
        )

    def load_policy_data(self, policy_name: str) -> dict[str, Any]:
        path = self._base_path / f"{policy_name}.yaml"
        if not path.is_file():
            raise FileNotFoundError(f"Policy 文件不存在: {path}")
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        if not isinstance(data, dict):
            raise ValueError(f"Policy 文件内容必须是对象: {path}")
        return data


class OpenFeaturePolicyProvider:
    """为后续动态控制平面预留的 provider 抽象。"""

    def load_policy_data(self, policy_name: str) -> dict[str, Any]:
        raise NotImplementedError(f"尚未实现 OpenFeature policy provider: {policy_name}")
