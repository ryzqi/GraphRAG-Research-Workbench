from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

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

def _escape_string(value: str) -> str:
    """转义字符串中的特殊字符，防止注入攻击。"""

    return re.sub(r'(["\\\'])', r"\\\1", value)


@dataclass(slots=True)
class MilvusSearchHit:
    chunk_id: str
    score: float


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

    async def _describe_fields(self) -> set[str]:
        describe = getattr(self._client, "describe_collection", None)
        if describe is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 describe_collection")

        info = await describe(collection_name=self._collection)
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

    async def _load_field_cache(self) -> None:
        if self._field_cache is not None:
            return
        self._field_cache = await self._describe_fields()

    def _required_fields(self) -> set[str]:
        return {
            "chunk_id",
            "kb_id",
            "material_id",
            "content",
            "context",
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
            FieldSchema(
                name="content",
                dtype=DataType.VARCHAR,
                max_length=65535,
                analyzer_params=analyzer_params,
            ),
            FieldSchema(name="context", dtype=DataType.VARCHAR, max_length=2048),
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

    def _build_filter_expr(self, kb_ids: list[str]) -> str | None:
        if not kb_ids:
            return None
        escaped_ids = [f"\"{_escape_string(kid)}\"" for kid in kb_ids]
        return f"kb_id in [{', '.join(escaped_ids)}]"

    async def ensure_collection(self, *, dim: int) -> None:
        """确保 collection 存在并对齐最新 schema。"""

        has_collection = getattr(self._client, "has_collection", None)
        create_collection = getattr(self._client, "create_collection", None)
        if has_collection is None or create_collection is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 has_collection/create_collection")

        exists = await has_collection(collection_name=self._collection)
        if exists:
            await self._load_field_cache()
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
            except Exception:
                index_params = None

        await create_collection(
            collection_name=self._collection,
            schema=schema,
            index_params=index_params,
        )

        self._field_cache = {
            "chunk_id",
            "kb_id",
            "material_id",
            "content",
            "context",
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
            else:
                chunk_id = getattr(entity, "chunk_id", None)
            score = float(getattr(hit, "distance", getattr(hit, "score", 0.0)))
            if chunk_id is not None:
                hits.append(MilvusSearchHit(chunk_id=str(chunk_id), score=score))
        return hits

    async def search(
        self, *, embedding: list[float], kb_ids: list[str], top_k: int = 5
    ) -> list[MilvusSearchHit]:
        """在指定 kb_ids 范围内检索相似 chunk_id（dense）。"""

        search = getattr(self._client, "search", None)
        if search is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 search")

        await self._load_field_cache()
        self._assert_schema_compatible()

        expr = self._build_filter_expr(kb_ids)
        res = await search(
            collection_name=self._collection,
            data=[embedding],
            anns_field=self._DEFAULT_VECTOR_FIELD,
            limit=top_k,
            output_fields=["chunk_id"],
            filter=expr,
            search_params={"metric_type": "COSINE", "params": {}},
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
    ) -> list[MilvusSearchHit]:
        """混合检索：dense + BM25。"""

        hybrid_search = getattr(self._client, "hybrid_search", None)
        if hybrid_search is None or AnnSearchRequest is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 hybrid_search/AnnSearchRequest")

        await self._load_field_cache()
        self._assert_schema_compatible()

        expr = self._build_filter_expr(kb_ids)
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

        ranker_key = ranker.lower()
        if ranker_key == "weighted" and WeightedRanker is not None:
            ranker_impl = WeightedRanker([dense_weight, sparse_weight])
        elif RRFRanker is not None:
            ranker_impl = RRFRanker(k=rrf_k)
        else:
            raise RuntimeError("pymilvus 缺少 ranker 实现")

        res = await hybrid_search(
            collection_name=self._collection,
            reqs=[dense_req, sparse_req],
            ranker=ranker_impl,
            limit=top_k,
            output_fields=["chunk_id"],
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
    ) -> None:
        """插入或更新单条向量记录。"""

        upsert = getattr(self._client, "upsert", None)
        if upsert is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 upsert")

        await self._load_field_cache()
        self._assert_schema_compatible()

        record = {
            "chunk_id": chunk_id,
            "kb_id": kb_id,
            "material_id": material_id,
            self._DEFAULT_VECTOR_FIELD: dense_vector,
            "content": content or "",
            "context": context or "",
        }
        await upsert(collection_name=self._collection, data=[record])

    async def upsert_batch(self, *, records: list[dict]) -> None:
        """批量插入或更新向量记录。"""

        if not records:
            return

        upsert = getattr(self._client, "upsert", None)
        if upsert is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 upsert")

        await self._load_field_cache()
        self._assert_schema_compatible()

        normalized_records = [self._normalize_record(r) for r in records]
        await upsert(collection_name=self._collection, data=normalized_records)

    async def delete_by_material(self, material_id: str) -> None:
        """删除指定资料的所有向量记录。"""

        delete = getattr(self._client, "delete", None)
        if delete is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 delete")

        escaped_id = _escape_string(material_id)
        await delete(
            collection_name=self._collection,
            filter=f"material_id == \"{escaped_id}\"",
        )

    async def delete_by_chunk_ids(self, chunk_ids: list[str]) -> None:
        """按 chunk_id 批量删除向量记录。"""

        delete = getattr(self._client, "delete", None)
        if delete is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 delete")
        if not chunk_ids:
            return

        escaped = [_escape_string(cid) for cid in chunk_ids]
        quoted = ", ".join(f"\"{cid}\"" for cid in escaped)
        await delete(
            collection_name=self._collection,
            filter=f"chunk_id in [{quoted}]",
        )


@lru_cache
def get_milvus_client() -> MilvusClient:
    """获取 Milvus 客户端单例（进程内复用）。"""

    return MilvusClient()

