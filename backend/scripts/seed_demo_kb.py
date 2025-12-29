"""Demo 种子脚本：创建知识库、资料、切片并写入 Milvus。

用法：
    cd backend
    uv run python scripts/seed_demo_kb.py
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import text

# 添加 src 到路径
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app.core.settings import get_settings
from app.db.session import async_engine, async_session_factory
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.milvus_client import MilvusClient
from app.models.document_chunk import DocumentChunk
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseStatus
from app.models.source_material import SourceMaterial, SourceType

# Demo 数据
DEMO_KB = {
    "name": "Python 编程知识库",
    "description": "包含 Python 编程基础知识和最佳实践",
    "tags": ["python", "编程", "教程"],
}

DEMO_MATERIALS = [
    {
        "title": "Python 基础语法",
        "source_type": SourceType.TEXT,
        "chunks": [
            "Python 是一种解释型、面向对象、动态数据类型的高级程序设计语言。Python 由 Guido van Rossum 于 1989 年底发明，第一个公开发行版发行于 1991 年。",
            "Python 的设计哲学强调代码的可读性和简洁的语法。相比于 C++ 或 Java，Python 让开发者能够用更少的代码表达想法。",
            "Python 支持多种编程范式，包括面向对象、命令式、函数式和过程式编程。它拥有动态类型系统和垃圾回收功能，能够自动管理内存使用。",
        ],
    },
    {
        "title": "Python 数据类型",
        "source_type": SourceType.TEXT,
        "chunks": [
            "Python 中的基本数据类型包括：整数（int）、浮点数（float）、字符串（str）、布尔值（bool）。这些是不可变类型。",
            "Python 的复合数据类型包括：列表（list）、元组（tuple）、字典（dict）、集合（set）。列表和字典是可变的，元组是不可变的。",
            "字符串在 Python 中是不可变的序列类型。可以使用单引号、双引号或三引号来定义字符串。字符串支持切片、拼接等操作。",
        ],
    },
    {
        "title": "Python 函数与模块",
        "source_type": SourceType.TEXT,
        "chunks": [
            "Python 使用 def 关键字定义函数。函数可以有参数和返回值。Python 支持默认参数、关键字参数、可变参数（*args）和关键字可变参数（**kwargs）。",
            "Python 模块是一个包含 Python 定义和语句的文件。模块可以定义函数、类和变量，也可以包含可执行的代码。使用 import 语句导入模块。",
            "Python 包是一种管理 Python 模块命名空间的形式，采用“点模块名称”。包目录下必须包含 __init__.py 文件，该文件可以为空。",
        ],
    },
]


async def seed() -> None:
    """执行种子数据填充。"""
    settings = get_settings()
    print(f"连接数据库: {settings.database_url[:50]}...")

    async with async_engine.begin() as conn:
        # 检查表是否存在
        result = await conn.execute(
            text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'knowledge_bases')")
        )
        if not result.scalar():
            print("错误：数据库表不存在，请先运行迁移：alembic upgrade head")
            return

    async with async_session_factory() as db:
        # 检查是否已有 demo 数据
        from sqlalchemy import select

        stmt = select(KnowledgeBase).where(KnowledgeBase.name == DEMO_KB["name"])
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            print(f"Demo 知识库已存在: {existing.id}")
            return

        # 创建知识库
        kb = KnowledgeBase(
            id=uuid.uuid4(),
            name=DEMO_KB["name"],
            description=DEMO_KB["description"],
            tags=DEMO_KB["tags"],
            status=KnowledgeBaseStatus.ACTIVE,
        )
        db.add(kb)
        await db.flush()
        print(f"创建知识库: {kb.id} - {kb.name}")

        # 初始化客户端
        embedding_client = EmbeddingClient()
        milvus_client = MilvusClient()

        # 收集所有 chunk 文本用于批量 embedding
        all_chunks: list[tuple[DocumentChunk, str]] = []

        for mat_data in DEMO_MATERIALS:
            # 创建资料
            material = SourceMaterial(
                id=uuid.uuid4(),
                kb_id=kb.id,
                source_type=mat_data["source_type"],
                title=mat_data["title"],
            )
            db.add(material)
            await db.flush()
            print(f"  创建资料: {material.id} - {material.title}")

            # 创建切片
            for idx, chunk_text in enumerate(mat_data["chunks"]):
                chunk = DocumentChunk(
                    id=uuid.uuid4(),
                    kb_id=kb.id,
                    material_id=material.id,
                    chunk_index=idx,
                    text=chunk_text,
                    locator={"material_title": material.title, "chunk_index": idx},
                    token_count=len(chunk_text),
                )
                db.add(chunk)
                all_chunks.append((chunk, chunk_text))
                print(f"    创建切片: {chunk.id} (index={idx})")

        await db.flush()

        # 批量生成 embedding
        print(f"\n生成 {len(all_chunks)} 个切片的 embedding...")
        texts = [text for _, text in all_chunks]

        try:
            embeddings = await embedding_client.embed(texts=texts)
            dim = len(embeddings[0])
            print(f"Embedding 维度: {dim}")

            # 确保 Milvus collection 存在
            await milvus_client.ensure_collection(dim=dim)

            # 写入 Milvus
            print("写入 Milvus...")
            insert = getattr(milvus_client._client, "insert", None)
            if insert is None:
                print("警告：pymilvus API 不匹配，跳过 Milvus 写入")
            else:
                data = []
                for (chunk, _), emb in zip(all_chunks, embeddings):
                    data.append({
                        "chunk_id": str(chunk.id),
                        "kb_id": str(chunk.kb_id),
                        "material_id": str(chunk.material_id),
                        "embedding": emb,
                    })
                await insert(collection_name=settings.milvus_collection, data=data)
                print(f"成功写入 {len(data)} 条向量")

        except Exception as e:
            print(f"警告：Embedding/Milvus 操作失败: {e}")
            print("数据库记录已创建，但向量未写入 Milvus")

        await db.commit()
        print(f"\n种子数据创建完成！知识库 ID: {kb.id}")


if __name__ == "__main__":
    asyncio.run(seed())
