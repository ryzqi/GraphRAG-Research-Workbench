from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.settings import get_settings

try:
    from pymilvus import AsyncMilvusClient  # type: ignore
except Exception:  # pragma: no cover
    AsyncMilvusClient = None  # type: ignore


def _escape_string(value: str) -> str:
    """转义字符串中的特殊字符，防止注入攻击。"""
    return re.sub(r'(["\\\'])', r'\\\1', value)


@dataclass(slots=True)
class MilvusSearchHit:
    chunk_id: str
    score: float


class MilvusClient:
    def __init__(self) -> None:
        settings = get_settings()
        if AsyncMilvusClient is None:
            raise RuntimeError("未检测到 pymilvus 的异步客户端，请确认依赖版本是否支持 AsyncMilvusClient")

        self._collection = settings.milvus_collection
        uri = f"http://{settings.milvus_host}:{settings.milvus_port}"
        self._client = AsyncMilvusClient(uri=uri)

    async def ensure_collection(self, *, dim: int) -> None:
        """确保 collection 存在（MVP：仅提供最小创建逻辑）。"""

        has_collection = getattr(self._client, "has_collection", None)
        create_collection = getattr(self._client, "create_collection", None)
        if has_collection is None or create_collection is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 has_collection/create_collection")

        if await has_collection(self._collection):
            return

        await create_collection(
            collection_name=self._collection,
            dimension=dim,
            primary_field_name="chunk_id",
            vector_field_name="embedding",
        )

    async def search(self, *, embedding: list[float], kb_ids: list[str], top_k: int = 5) -> list[MilvusSearchHit]:
        """在指定 kb_ids 范围内检索相似 chunk_id（返回 chunk_id + score）。"""

        search = getattr(self._client, "search", None)
        if search is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 search")

        # 使用参数化方式构建过滤表达式，防止注入
        expr = None
        if kb_ids:
            escaped_ids = [f'"{_escape_string(kid)}"' for kid in kb_ids]
            expr = f"kb_id in [{', '.join(escaped_ids)}]"
        res = await search(
            collection_name=self._collection,
            data=[embedding],
            limit=top_k,
            output_fields=["chunk_id"],
            filter=expr,
        )

        hits: list[MilvusSearchHit] = []
        for hit in (res[0] if res else []):
            entity = getattr(hit, "entity", None) or {}
            chunk_id = entity.get("chunk_id") if isinstance(entity, dict) else getattr(entity, "chunk_id", None)
            score = float(getattr(hit, "distance", getattr(hit, "score", 0.0)))
            if chunk_id is not None:
                hits.append(MilvusSearchHit(chunk_id=str(chunk_id), score=score))
        return hits

    async def upsert(
        self,
        *,
        chunk_id: str,
        kb_id: str,
        material_id: str,
        embedding: list[float],
    ) -> None:
        """插入或更新单条向量记录。"""
        upsert = getattr(self._client, "upsert", None)
        if upsert is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 upsert")

        await upsert(
            collection_name=self._collection,
            data=[
                {
                    "chunk_id": chunk_id,
                    "kb_id": kb_id,
                    "material_id": material_id,
                    "embedding": embedding,
                }
            ],
        )

    async def upsert_batch(
        self,
        *,
        records: list[dict],
    ) -> None:
        """批量插入或更新向量记录。"""
        if not records:
            return

        upsert = getattr(self._client, "upsert", None)
        if upsert is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 upsert")

        await upsert(collection_name=self._collection, data=records)

    async def delete_by_material(self, material_id: str) -> None:
        """删除指定资料的所有向量记录。"""
        delete = getattr(self._client, "delete", None)
        if delete is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 delete")

        # 转义 material_id 防止注入
        escaped_id = _escape_string(material_id)
        await delete(
            collection_name=self._collection,
            filter=f'material_id == "{escaped_id}"',
        )
