"""ORM 模型。

导入任意 `app.models.*` 子模块时，确保所有模型已被加载，
以避免 SQLAlchemy relationship 字符串解析失败（例如：relationship("KnowledgeBase")）。
"""

from __future__ import annotations

from app.db.base import import_all_models

# 确保所有模型都被导入，并注册到 DeclarativeBase 的 registry。
import_all_models()
