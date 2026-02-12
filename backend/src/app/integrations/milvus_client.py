from __future__ import annotations

import re
import inspect
import logging
from dataclasses import dataclass

from app.core.settings import get_settings

try:
    from pymilvus import (
        AnnSearchRequest,
        AsyncMilvusClient,
        CollectionSchema,
        DataType,
        FieldSchema,
        Function,
        FunctionType,
        RRFRanker,
        WeightedRanker,
    )
    from pymilvus.milvus_client.index import IndexParams
except Exception:  # pragma: no cover
    AnnSearchRequest = None  # type: ignore
    AsyncMilvusClient = None  # type: ignore
    CollectionSchema = None  # type: ignore
    DataType = None  # type: ignore
    FieldSchema = None  # type: ignore
    Function = None  # type: ignore
    FunctionType = None  # type: ignore
    RRFRanker = None  # type: ignore
    WeightedRanker = None  # type: ignore
    IndexParams = None  # type: ignore

logger = logging.getLogger(__name__)

def _escape_string(value: str) -> str:
    """转义字符串中的特殊字符，防止注入攻击。"""

    return re.sub(r'(["\\\'])', r"\\\1", value)


def _build_weighted_ranker(
    weights: list[float],
    reqs: list[AnnSearchRequest],
):
    if WeightedRanker is None:
        raise RuntimeError("pymilvus 缺少 WeightedRanker")
    if len(weights) != len(reqs):
        raise ValueError(f"权重数量({len(weights)})与 reqs 数量({len(reqs)})不一致")
    return WeightedRanker(*weights)


@dataclass(slots=True)
class MilvusSearchHit:
    chunk_id: str
    score: float
    kb_id: str | None = None
    material_id: str | None = None
    chunk_role: str | None = None
    parent_chunk_id: str | None = None
    child_seq: int | None = None
    content: str | None = None
    context: str | None = None
    locator: dict | None = None
    metadata: dict | None = None


class MilvusClient:
    """Milvus 异步客户端封装（仅保留最新实现）。"""

    _DEFAULT_VECTOR_FIELD = "dense_vector"
    _SPARSE_FIELD = "sparse_vector"

    def __init__(self) -> None:
        settings = get_settings()
        if AsyncMilvusClient is None:
            raise RuntimeError("未检测到 pymilvus 的异步客户端，请确认依赖是否正确安装")

        self._settings = settings
        self._collection = settings.milvus_collection
        uri = f"http://{settings.milvus_host}:{settings.milvus_port}"
        self._client = AsyncMilvusClient(uri=uri)
        self._field_cache: set[str] | None = None

    async def aclose(self) -> None:
        """关闭 Milvus 异步客户端。"""
        close = getattr(self._client, "close", None)
        if close is None:
            logger.warning("pymilvus API 不匹配：缺少 close")
            return
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Milvus client close 失败", extra={"error": str(exc)})

    async def ready_check(self) -> None:
        """就绪探测：调用可用的 Milvus API 验证连接。"""
        describe = getattr(self._client, "describe_collection", None)
        if describe is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 describe_collection")
        await describe(collection_name=self._collection)

    async def _describe_fields(
        self,
        *,
        collection_name: str | None = None,
    ) -> set[str]:
        describe = getattr(self._client, "describe_collection", None)
        if describe is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 describe_collection")

        target_collection = collection_name or self._collection
        info = await describe(collection_name=target_collection)
        if not isinstance(info, dict):
            raise RuntimeError("pymilvus describe_collection 返回类型异常，预期为 dict")

        schema = info.get("schema") or {}
        fields = schema.get("fields") or info.get("fields") or []

        names: set[str] = set()
        for field in fields:
            if isinstance(field, dict):
                name = field.get("name")
            else:
                name = getattr(field, "name", None)
            if name:
                names.add(str(name))
        return names

    async def _load_field_cache(
        self,
        *,
        collection_name: str | None = None,
    ) -> None:
        if self._field_cache is not None:
            return
        self._field_cache = await self._describe_fields(
            collection_name=collection_name
        )

    def _required_fields(self) -> set[str]:
        return {
            "chunk_id",
            "kb_id",
            "material_id",
            "chunk_role",
            "parent_chunk_id",
            "child_seq",
            "content",
            "context",
            "locator",
            "metadata",
            self._DEFAULT_VECTOR_FIELD,
            self._SPARSE_FIELD,
        }

    def _assert_schema_compatible(self) -> None:
        if self._field_cache is None:
            return
        missing = self._required_fields() - self._field_cache
        if not missing:
            return
        missing_str = ", ".join(sorted(missing))
        raise RuntimeError(
            "Milvus schema 与当前代码不兼容，缺少字段："
            f"{missing_str}。请重建 collection 并重导入数据。"
        )

    def supports_hybrid_search(self) -> bool:
        hybrid = getattr(self._client, "hybrid_search", None)
        return (
            hybrid is not None
            and AnnSearchRequest is not None
            and (RRFRanker is not None or WeightedRanker is not None)
        )

    def _require_schema_types(self) -> None:
        if CollectionSchema is None or FieldSchema is None or DataType is None:
            raise RuntimeError("pymilvus 缺少 schema 相关类型，请升级 pymilvus")

    def _bm25_supported(self) -> bool:
        return Function is not None and FunctionType is not None and hasattr(FunctionType, "BM25")

    def _build_schema(self, dim: int):
        self._require_schema_types()

        analyzer_params = {"type": self._settings.milvus_text_analyzer}
        if self._settings.milvus_text_analyzer_filters:
            analyzer_params["filter"] = self._settings.milvus_text_analyzer_filters

        fields = [
            FieldSchema(
                name="chunk_id",
                dtype=DataType.VARCHAR,
                is_primary=True,
                max_length=64,
            ),
            FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="material_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="chunk_role", dtype=DataType.VARCHAR, max_length=16),
            FieldSchema(
                name="parent_chunk_id", dtype=DataType.VARCHAR, max_length=64
            ),
            FieldSchema(name="child_seq", dtype=DataType.INT32),
            FieldSchema(
                name="content",
                dtype=DataType.VARCHAR,
                max_length=65535,
                enable_analyzer=True,
                analyzer_params=analyzer_params,
            ),
            FieldSchema(name="context", dtype=DataType.VARCHAR, max_length=2048),
            FieldSchema(name="locator", dtype=DataType.JSON),
            FieldSchema(name="metadata", dtype=DataType.JSON),
            FieldSchema(
                name=self._DEFAULT_VECTOR_FIELD,
                dtype=DataType.FLOAT_VECTOR,
                dim=dim,
            ),
            FieldSchema(name=self._SPARSE_FIELD, dtype=DataType.SPARSE_FLOAT_VECTOR),
        ]

        functions = None
        if self._bm25_supported():
            try:
                functions = [
                    Function(
                        name="bm25_fn",
                        function_type=FunctionType.BM25,
                        input_field_names=["content"],
                        output_field_names=[self._SPARSE_FIELD],
                    )
                ]
            except Exception:
                functions = None

        return CollectionSchema(
            fields=fields,
            description="kb chunks with hybrid retrieval",
            functions=functions,
        )

    def _build_filter_expr(self, kb_ids: list[str], extra_expr: str | None = None) -> str | None:
        """Build a safe filter expression for Milvus.

        - Always enforces kb_id scope when provided.
        - Allows an optional extra expression hook (e.g. subject/tenant filters) which
          MUST be pre-sanitized by callers.
        """

        expr = None
        if kb_ids:
            escaped_ids = [f"\"{_escape_string(kid)}\"" for kid in kb_ids]
            expr = f"kb_id in [{', '.join(escaped_ids)}]"

        extra = (extra_expr or "").strip()
        if not extra:
            return expr
        if not expr:
            return extra
        return f"({expr}) and ({extra})"

    async def ensure_collection(
        self,
        *,
        dim: int,
        collection_name: str | None = None,
    ) -> None:
        """确保 collection 存在并对齐最新 schema。"""

        has_collection = getattr(self._client, "has_collection", None)
        create_collection = getattr(self._client, "create_collection", None)
        if has_collection is None or create_collection is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 has_collection/create_collection")

        target_collection = collection_name or self._collection
        exists = await has_collection(collection_name=target_collection)
        if exists:
            await self._load_field_cache(collection_name=target_collection)
            self._assert_schema_compatible()
            return

        schema = self._build_schema(dim)

        index_params = None
        if IndexParams is not None:
            try:
                index_params = IndexParams()
                index_params.add_index(
                    self._DEFAULT_VECTOR_FIELD,
                    index_type="AUTOINDEX",
                    metric_type="COSINE",
                )
                if self._bm25_supported():
                    index_params.add_index(
                        self._SPARSE_FIELD,
                        index_type="SPARSE_INVERTED_INDEX",
                        metric_type="BM25",
                        params={
                            "inverted_index_algo": "DAAT_MAXSCORE",
                            "bm25_k1": 1.2,
                            "bm25_b": 0.75,
                        },
                    )
            except Exception:
                index_params = None

        try:
            await create_collection(
                collection_name=target_collection,
                schema=schema,
                index_params=index_params,
            )
        except Exception as exc:
            bm25_enabled = self._bm25_supported()
            logger.exception(
                "Milvus create_collection 失败",
                extra={
                    "collection_name": target_collection,
                    "bm25_enabled": bm25_enabled,
                },
            )
            raise RuntimeError(
                "Milvus create_collection 失败："
                f"collection={target_collection}, bm25_enabled={bm25_enabled}, error={exc}。"
                "若启用 BM25，请确认 content 字段已设置 enable_analyzer=True；"
                "如为旧 schema，请清空并重建 collection 后重试。"
            ) from exc

        self._field_cache = {
            "chunk_id",
            "kb_id",
            "material_id",
            "chunk_role",
            "parent_chunk_id",
            "child_seq",
            "content",
            "context",
            "locator",
            "metadata",
            self._DEFAULT_VECTOR_FIELD,
            self._SPARSE_FIELD,
        }

    def _parse_hits(self, res) -> list[MilvusSearchHit]:
        hits: list[MilvusSearchHit] = []
        if not res:
            return hits
        group = res[0] if isinstance(res, list) else res
        for hit in group or []:
            entity = getattr(hit, "entity", None) or {}
            if isinstance(entity, dict):
                chunk_id = entity.get("chunk_id")
                kb_id = entity.get("kb_id")
                material_id = entity.get("material_id")
                chunk_role = entity.get("chunk_role")
                parent_chunk_id = entity.get("parent_chunk_id")
                child_seq = entity.get("child_seq")
                content = entity.get("content")
                context = entity.get("context")
                locator = entity.get("locator")
                metadata = entity.get("metadata")
            else:
                chunk_id = getattr(entity, "chunk_id", None)
                kb_id = getattr(entity, "kb_id", None)
                material_id = getattr(entity, "material_id", None)
                chunk_role = getattr(entity, "chunk_role", None)
                parent_chunk_id = getattr(entity, "parent_chunk_id", None)
                child_seq = getattr(entity, "child_seq", None)
                content = getattr(entity, "content", None)
                context = getattr(entity, "context", None)
                locator = getattr(entity, "locator", None)
                metadata = getattr(entity, "metadata", None)
            score = float(getattr(hit, "distance", getattr(hit, "score", 0.0)))
            if chunk_id is not None:
                hits.append(
                    MilvusSearchHit(
                        chunk_id=str(chunk_id),
                        score=score,
                        kb_id=str(kb_id) if kb_id is not None else None,
                        material_id=str(material_id) if material_id is not None else None,
                        chunk_role=str(chunk_role) if chunk_role is not None else None,
                        parent_chunk_id=str(parent_chunk_id) if parent_chunk_id is not None else None,
                        child_seq=int(child_seq) if child_seq is not None else None,
                        content=str(content) if content is not None else None,
                        context=str(context) if context is not None else None,
                        locator=locator if isinstance(locator, dict) else locator,
                        metadata=metadata if isinstance(metadata, dict) else metadata,
                    )
                )
        return hits

    async def search(
        self,
        *,
        embedding: list[float],
        kb_ids: list[str],
        top_k: int = 5,
        extra_filter_expr: str | None = None,
        collection_name: str | None = None,
    ) -> list[MilvusSearchHit]:
        """在指定 kb_ids 范围内检索相似 chunk_id（dense）。"""

        search = getattr(self._client, "search", None)
        if search is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 search")

        target_collection = collection_name or self._collection
        await self._load_field_cache(collection_name=target_collection)
        self._assert_schema_compatible()

        expr = self._build_filter_expr(kb_ids, extra_filter_expr)
        res = await search(
            collection_name=target_collection,
            data=[embedding],
            anns_field=self._DEFAULT_VECTOR_FIELD,
            limit=top_k,
            output_fields=[
                "chunk_id",
                "kb_id",
                "material_id",
                "chunk_role",
                "parent_chunk_id",
                "child_seq",
                "content",
                "context",
                "locator",
                "metadata",
            ],
            filter=expr,
            search_params={"metric_type": "COSINE", "params": {}},
        )
        return self._parse_hits(res)

    async def bm25_search(
        self,
        *,
        query: str,
        kb_ids: list[str],
        top_k: int = 5,
        extra_filter_expr: str | None = None,
        collection_name: str | None = None,
    ) -> list[MilvusSearchHit]:
        """BM25 keyword retrieval (sparse) within kb_ids scope."""

        search = getattr(self._client, "search", None)
        if search is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 search")

        target_collection = collection_name or self._collection
        await self._load_field_cache(collection_name=target_collection)
        self._assert_schema_compatible()

        expr = self._build_filter_expr(kb_ids, extra_filter_expr)
        res = await search(
            collection_name=target_collection,
            data=[query],
            anns_field=self._SPARSE_FIELD,
            limit=top_k,
            output_fields=[
                "chunk_id",
                "kb_id",
                "material_id",
                "chunk_role",
                "parent_chunk_id",
                "child_seq",
                "content",
                "context",
                "locator",
                "metadata",
            ],
            filter=expr,
            search_params={"metric_type": "BM25"},
        )
        return self._parse_hits(res)

    async def hybrid_search(
        self,
        *,
        embedding: list[float],
        query: str,
        kb_ids: list[str],
        top_k: int = 5,
        ranker: str = "rrf",
        dense_weight: float = 0.7,
        sparse_weight: float = 0.3,
        rrf_k: int = 60,
        extra_filter_expr: str | None = None,
        collection_name: str | None = None,
    ) -> list[MilvusSearchHit]:
        """混合检索：dense + BM25。"""

        hybrid_search = getattr(self._client, "hybrid_search", None)
        if hybrid_search is None or AnnSearchRequest is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 hybrid_search/AnnSearchRequest")

        target_collection = collection_name or self._collection
        await self._load_field_cache(collection_name=target_collection)
        self._assert_schema_compatible()

        expr = self._build_filter_expr(kb_ids, extra_filter_expr)
        dense_req = AnnSearchRequest(
            data=[embedding],
            anns_field=self._DEFAULT_VECTOR_FIELD,
            param={"metric_type": "COSINE", "params": {}},
            limit=top_k,
            expr=expr,
        )
        sparse_req = AnnSearchRequest(
            data=[query],
            anns_field=self._SPARSE_FIELD,
            param={"metric_type": "BM25"},
            limit=top_k,
            expr=expr,
        )

        reqs = [dense_req, sparse_req]
        ranker_key = ranker.lower()
        if ranker_key == "weighted":
            weights = [dense_weight, sparse_weight]
            ranker_impl = _build_weighted_ranker(weights, reqs)
        elif RRFRanker is not None:
            ranker_impl = RRFRanker(k=rrf_k)
        else:
            raise RuntimeError("pymilvus 缺少 ranker 实现")

        res = await hybrid_search(
            collection_name=target_collection,
            reqs=reqs,
            ranker=ranker_impl,
            limit=top_k,
            output_fields=[
                "chunk_id",
                "kb_id",
                "material_id",
                "chunk_role",
                "parent_chunk_id",
                "child_seq",
                "content",
                "context",
                "locator",
                "metadata",
            ],
        )
        return self._parse_hits(res)

    def _assert_record_shape(self, record: dict) -> None:
        required = {"chunk_id", "kb_id", "material_id", self._DEFAULT_VECTOR_FIELD}
        missing = required - set(record.keys())
        if missing:
            missing_str = ", ".join(sorted(missing))
            raise KeyError(
                f"Milvus upsert 记录缺少必要字段：{missing_str}（仅支持最新写入格式）"
            )

    def _normalize_record(self, record: dict) -> dict:
        self._assert_record_shape(record)
        normalized = dict(record)
        if "content" not in normalized:
            normalized["content"] = ""
        if "context" not in normalized:
            normalized["context"] = ""
        if "chunk_role" not in normalized:
            normalized["chunk_role"] = "default"
        if "parent_chunk_id" not in normalized:
            normalized["parent_chunk_id"] = ""
        if "child_seq" not in normalized:
            normalized["child_seq"] = 0
        if "locator" not in normalized:
            normalized["locator"] = {}
        if "metadata" not in normalized:
            normalized["metadata"] = {}
        return normalized

    async def upsert(
        self,
        *,
        chunk_id: str,
        kb_id: str,
        material_id: str,
        dense_vector: list[float],
        content: str | None = None,
        context: str | None = None,
        chunk_role: str = "default",
        parent_chunk_id: str | None = None,
        child_seq: int | None = None,
        locator: dict | None = None,
        metadata: dict | None = None,
        collection_name: str | None = None,
    ) -> None:
        """插入或更新单条向量记录。"""

        upsert = getattr(self._client, "upsert", None)
        if upsert is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 upsert")

        target_collection = collection_name or self._collection
        await self._load_field_cache(collection_name=target_collection)
        self._assert_schema_compatible()

        record = {
            "chunk_id": chunk_id,
            "kb_id": kb_id,
            "material_id": material_id,
            self._DEFAULT_VECTOR_FIELD: dense_vector,
            "content": content or "",
            "context": context or "",
            "chunk_role": chunk_role,
            "parent_chunk_id": parent_chunk_id or "",
            "child_seq": child_seq or 0,
            "locator": locator or {},
            "metadata": metadata or {},
        }
        await upsert(collection_name=target_collection, data=[record])

    async def upsert_batch(
        self,
        *,
        records: list[dict],
        collection_name: str | None = None,
    ) -> None:
        """批量插入或更新向量记录。"""

        if not records:
            return

        upsert = getattr(self._client, "upsert", None)
        if upsert is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 upsert")

        target_collection = collection_name or self._collection
        await self._load_field_cache(collection_name=target_collection)
        self._assert_schema_compatible()

        normalized_records = [self._normalize_record(r) for r in records]
        await upsert(collection_name=target_collection, data=normalized_records)

    async def delete_by_material(
        self,
        material_id: str,
        *,
        collection_name: str | None = None,
    ) -> None:
        """删除指定资料的所有向量记录。"""

        await self.delete_by_expr(
            f"material_id == \"{_escape_string(material_id)}\"",
            collection_name=collection_name,
        )

    async def delete_by_kb_id(
        self,
        kb_id: str,
        *,
        collection_name: str | None = None,
    ) -> None:
        """删除指定知识库的所有向量记录。"""

        await self.delete_by_expr(
            f"kb_id == \"{_escape_string(kb_id)}\"",
            collection_name=collection_name,
        )

    async def delete_by_expr(
        self,
        expr: str,
        *,
        collection_name: str | None = None,
    ) -> None:
        """按表达式删除向量记录。"""

        delete = getattr(self._client, "delete", None)
        if delete is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 delete")

        target_collection = collection_name or self._collection
        await delete(
            collection_name=target_collection,
            filter=expr,
        )

    async def delete_by_chunk_ids(
        self,
        chunk_ids: list[str],
        *,
        collection_name: str | None = None,
    ) -> None:
        """按 chunk_id 批量删除向量记录。"""

        delete = getattr(self._client, "delete", None)
        if delete is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 delete")
        if not chunk_ids:
            return

        escaped = [_escape_string(cid) for cid in chunk_ids]
        quoted = ", ".join(f"\"{cid}\"" for cid in escaped)
        target_collection = collection_name or self._collection
        await delete(
            collection_name=target_collection,
            filter=f"chunk_id in [{quoted}]",
        )

    async def query_by_chunk_ids(
        self,
        *,
        chunk_ids: list[str],
        output_fields: list[str] | None = None,
        collection_name: str | None = None,
    ) -> list[dict]:
        """按 chunk_id 批量查询向量记录。"""

        query = getattr(self._client, "query", None)
        if query is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 query")
        if not chunk_ids:
            return []

        target_collection = collection_name or self._collection
        await self._load_field_cache(collection_name=target_collection)
        self._assert_schema_compatible()

        escaped = [_escape_string(cid) for cid in chunk_ids]
        quoted = ", ".join(f"\"{cid}\"" for cid in escaped)
        fields = output_fields or [
            "chunk_id",
            "kb_id",
            "material_id",
            "chunk_role",
            "parent_chunk_id",
            "child_seq",
            "content",
            "context",
            "locator",
            "metadata",
        ]
        res = await query(
            collection_name=target_collection,
            filter=f"chunk_id in [{quoted}]",
            output_fields=fields,
        )
        if isinstance(res, list):
            return res
        return []


def create_milvus_client() -> MilvusClient:
    """创建 Milvus 客户端实例。"""
    return MilvusClient()

