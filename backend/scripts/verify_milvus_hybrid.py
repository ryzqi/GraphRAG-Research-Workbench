"""最小 Milvus hybrid 验证脚本（需要本地 Milvus）。"""

from __future__ import annotations

import asyncio

from app.core.settings import get_settings
from app.integrations.milvus_client import MilvusClient


async def main() -> None:
    settings = get_settings()
    client = MilvusClient()
    dim = settings.embedding_dim or 3

    supported = client.supports_hybrid_search()
    print(f"Hybrid 支持: {supported}")
    await client.ensure_collection(dim=dim)

    if not supported:
        print("当前环境不支持 hybrid_search，跳过示例查询")
        return

    record = {
        "chunk_id": "demo-1",
        "kb_id": "kb-demo",
        "material_id": "mat-demo",
        "content": "混合检索示例文本",
        "context": "demo",
        "embedding": [0.1] * dim,
    }
    await client.upsert_batch(records=[record])

    hits = await client.hybrid_search(
        embedding=[0.1] * dim,
        query="示例",
        kb_ids=["kb-demo"],
        top_k=3,
    )
    print("Hybrid hits:", hits)


if __name__ == "__main__":
    asyncio.run(main())
