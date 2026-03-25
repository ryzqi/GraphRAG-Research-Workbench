"""提示词加载器。

从 YAML 文件加载提示词模板，支持变量渲染和 few-shot 示例。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class PromptTemplate(BaseModel):
    """提示词模板。"""

    version: str
    name: str
    description: str
    template: str
    variables: list[dict[str, Any]] = []
    few_shot_examples: list[dict[str, str]] = []


class PromptLoader:
    """提示词加载器（单例）。"""

    _instance: PromptLoader | None = None
    _templates: dict[str, PromptTemplate]

    def __new__(cls) -> PromptLoader:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._templates = {}
            cls._instance._load_all()
        return cls._instance

    def _load_all(self) -> None:
        """加载所有模板。"""
        base_path = Path(__file__).parent / "templates"
        if not base_path.exists():
            return

        for yaml_file in base_path.rglob("*.yaml"):
            rel_path = yaml_file.relative_to(base_path)
            key = str(rel_path.with_suffix("")).replace("\\", "/")
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                self._templates[key] = PromptTemplate(**data)

    def get(self, key: str) -> PromptTemplate:
        """获取模板。"""
        if key not in self._templates:
            raise KeyError(f"Prompt 模板不存在: {key}")
        return self._templates[key]

    def render(self, key: str, **kwargs: Any) -> str:
        """渲染模板。"""
        template = self.get(key)
        return template.template.format(**kwargs)

    def render_with_few_shot(self, key: str, **kwargs: Any) -> str:
        """渲染模板（含 few-shot 示例）。"""
        template = self.get(key)
        base = template.template.format(**kwargs)

        if not template.few_shot_examples:
            return base

        examples = "\n\n".join(
            f"示例输入: {ex.get('input', '')}\n示例输出: {ex.get('output', '')}"
            for ex in template.few_shot_examples
        )
        return f"{base}\n\n参考示例:\n{examples}"

    def reload(self) -> None:
        """重新加载所有模板。"""
        self._templates.clear()
        self._load_all()


@lru_cache
def get_prompt_loader() -> PromptLoader:
    """获取 PromptLoader 实例。"""
    return PromptLoader()
