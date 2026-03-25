from __future__ import annotations


class ModelConfigIncompleteError(RuntimeError):
    """当模型运行时配置缺少必填字段时抛出。"""

