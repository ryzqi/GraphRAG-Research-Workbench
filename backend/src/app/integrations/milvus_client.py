from __future__ import annotations

import inspect
import logging
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

logger = logging.getLogger(__name__)


def _escape_string(value: str) -> str:
    """转义字符串中的特殊字符，防止注入攻击。"""
    return re.sub(r'(["\\\'])', r'\\\1', value)


@dataclass(slots=True)
class MilvusSearchHit:
    chunk_id: str
    score: float


class MilvusClient:
    _DEFAULT_VECTOR_FIELD = "dense_vector"
    _LEGACY_VECTOR_FIELD = "embedding"
    _SPARSE_FIELD = "sparse_vector"

    def __init__(self) -> None:
        settings = get_settings()
        if AsyncMilvusClient is None:
            raise RuntimeError("未检测到 pymilvus 的异步客户端，请确认依赖版本是否支持 AsyncMilvusClient")

        self._settings = settings
        self._collection = settings.milvus_collection
        uri = f"http://{settings.milvus_host}:{settings.milvus_port}"
        self._client = AsyncMilvusClient(uri=uri)
        self._vector_field = self._DEFAULT_VECTOR_FIELD
        self._field_cache: set[str] | None = None

    async def _call_with_signature(self, func, **kwargs):
        sig = inspect.signature(func)
        filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
        return await func(**filtered)

    async def _describe_fields(self) -> set[str] | None:
        describe = getattr(self._client, "describe_collection", None)
        if describe is None:
            return None
        try:
            info = await self._call_with_signature(
                describe, collection_name=self._collection
            )
        except Exception:
            return None

        fields = []
        if isinstance(info, dict):
            schema = info.get("schema") or {}
            fields = schema.get("fields") or info.get("fields") or []
        else:
            schema = getattr(info, "schema", None)
            fields = getattr(schema, "fields", None) or getattr(info, "fields", None) or []

        names: set[str] = set()
        for field in fields:
            if isinstance(field, dict):
                name = field.get("name")
            else:
                name = getattr(field, "name", None)
            if name:
                names.add(str(name))
        return names

    async def _resolve_vector_field(self) -> None:
        if self._field_cache is not None:
            return
        fields = await self._describe_fields()
        if fields:
            self._field_cache = fields
            if self._DEFAULT_VECTOR_FIELD in fields:
                self._vector_field = self._DEFAULT_VECTOR_FIELD
            elif self._LEGACY_VECTOR_FIELD in fields:
                self._vector_field = self._LEGACY_VECTOR_FIELD
        else:
            self._field_cache = set()

    def supports_hybrid_search(self) -> bool:
        hybrid = getattr(self._client, "hybrid_search", None)
        return (
            hybrid is not None
            and AnnSearchRequest is not None
            and (RRFRanker is not None or WeightedRanker is not None)
        )

    def _schema_supported(self) -> bool:
        return CollectionSchema is not None and FieldSchema is not None and DataType is not None

    def _bm25_supported(self) -> bool:
        return Function is not None and FunctionType is not None

    def _build_schema(self, dim: int):
        if not self._schema_supported():
            raise RuntimeError("pymilvus 缺少 schema 相关类型，无法创建完整 schema")

        analyzer_params = {"type": self._settings.milvus_text_analyzer}
        if self._settings.milvus_text_analyzer_filters:
            analyzer_params["filter"] = self._settings.milvus_text_analyzer_filters

        content_kwargs = {
            "name": "content",
            "dtype": DataType.VARCHAR,
            "max_length": 65535,
            "analyzer_params": analyzer_params,
        }
        try:
            content_field = FieldSchema(**content_kwargs)
        except TypeError:
            content_kwargs.pop("analyzer_params", None)
            content_field = FieldSchema(**content_kwargs)

        fields = [
            FieldSchema(
                name="chunk_id",
                dtype=DataType.VARCHAR,
                is_primary=True,
                max_length=64,
            ),
            FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="material_id", dtype=DataType.VARCHAR, max_length=64),
            content_field,
            FieldSchema(name="context", dtype=DataType.VARCHAR, max_length=2048),
            FieldSchema(name=self._DEFAULT_VECTOR_FIELD, dtype=DataType.FLOAT_VECTOR, dim=dim),
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

        try:
            return CollectionSchema(
                fields=fields,
                description="kb chunks with hybrid retrieval",
                functions=functions,
            )
        except TypeError:
            return CollectionSchema(fields=fields, description="kb chunks with hybrid retrieval")

    def _build_filter_expr(self, kb_ids: list[str]) -> str | None:
        if not kb_ids:
            return None
        escaped_ids = [f'"{_escape_string(kid)}"' for kid in kb_ids]
        return f"kb_id in [{', '.join(escaped_ids)}]"

    def _warn_if_schema_incompatible(self) -> None:
        if not self._field_cache:
            return
        required = {"chunk_id", "kb_id", "material_id", self._vector_field}
        if self._settings.retrieval_hybrid_enabled:
            required.update({"content", self._SPARSE_FIELD})
        if self._settings.ingestion_contextual_enabled:
            required.add("context")
        missing = required - self._field_cache
        if missing:
            logger.warning(
                "Milvus schema 与当前配置不匹配，需要重建",
                extra={"missing_fields": sorted(missing)},
            )

    async def _create_index_if_supported(self) -> None:
        create_index = getattr(self._client, "create_index", None)
        if create_index is None:
            return
        try:
            await self._call_with_signature(
                create_index,
                collection_name=self._collection,
                field_name=self._vector_field,
                index_params={
                    "index_type": "AUTOINDEX",
                    "metric_type": "COSINE",
                    "params": {},
                },
            )
        except Exception as exc:
            logger.warning("Milvus 索引创建失败", extra={"error": str(exc)})

    async def ensure_collection(self, *, dim: int) -> None:
        """确保 collection 存在并尽量对齐 schema。"""
        has_collection = getattr(self._client, "has_collection", None)
        create_collection = getattr(self._client, "create_collection", None)
        if has_collection is None or create_collection is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 has_collection/create_collection")

        if self._settings.retrieval_hybrid_enabled and not self.supports_hybrid_search():
            logger.warning("当前 pymilvus 不支持 hybrid_search")
        if self._settings.retrieval_hybrid_enabled and not self._bm25_supported():
            logger.warning("当前 pymilvus 不支持 BM25 Function")

        exists = await self._call_with_signature(
            has_collection, collection_name=self._collection
        )
        if exists:
            await self._resolve_vector_field()
            self._warn_if_schema_incompatible()
            return

        if self._schema_supported():
            schema = self._build_schema(dim)
            await self._call_with_signature(
                create_collection, collection_name=self._collection, schema=schema
            )
            self._vector_field = self._DEFAULT_VECTOR_FIELD
            self._field_cache = {
                "chunk_id",
                "kb_id",
                "material_id",
                "content",
                "context",
                self._DEFAULT_VECTOR_FIELD,
                self._SPARSE_FIELD,
            }
            await self._create_index_if_supported()
            return

        await self._call_with_signature(
            create_collection,
            collection_name=self._collection,
            dimension=dim,
            primary_field_name="chunk_id",
            vector_field_name=self._LEGACY_VECTOR_FIELD,
        )
        self._vector_field = self._LEGACY_VECTOR_FIELD
        self._field_cache = {"chunk_id", "kb_id", "material_id", self._LEGACY_VECTOR_FIELD}

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

        await self._resolve_vector_field()
        expr = self._build_filter_expr(kb_ids)
        res = await self._call_with_signature(
            search,
            collection_name=self._collection,
            data=[embedding],
            anns_field=self._vector_field,
            limit=top_k,
            output_fields=["chunk_id"],
            filter=expr,
            param={"metric_type": "COSINE", "params": {}},
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

        await self._resolve_vector_field()
        expr = self._build_filter_expr(kb_ids)
        dense_req = AnnSearchRequest(
            data=[embedding],
            anns_field=self._vector_field,
            param={"metric_type": "COSINE", "params": {}},
            limit=top_k,
            expr=expr,
            output_fields=["chunk_id"],
        )
        sparse_req = AnnSearchRequest(
            data=[query],
            anns_field=self._SPARSE_FIELD,
            param={"metric_type": "BM25"},
            limit=top_k,
            expr=expr,
            output_fields=["chunk_id"],
        )

        ranker_key = ranker.lower()
        if ranker_key == "weighted" and WeightedRanker is not None:
            ranker_impl = WeightedRanker([dense_weight, sparse_weight])
        elif RRFRanker is not None:
            ranker_impl = RRFRanker(k=rrf_k)
        else:
            raise RuntimeError("pymilvus 缺少 ranker 实现")

        res = await self._call_with_signature(
            hybrid_search,
            collection_name=self._collection,
            reqs=[dense_req, sparse_req],
            ranker=ranker_impl,
            output_fields=["chunk_id"],
        )
        return self._parse_hits(res)

    async def _normalize_record(self, record: dict) -> dict:
        await self._resolve_vector_field()
        normalized = dict(record)
        if "embedding" in normalized and self._vector_field != self._LEGACY_VECTOR_FIELD:
            normalized[self._vector_field] = normalized.pop("embedding")
        if (
            self._vector_field == self._LEGACY_VECTOR_FIELD
            and self._DEFAULT_VECTOR_FIELD in normalized
        ):
            normalized[self._LEGACY_VECTOR_FIELD] = normalized.pop(
                self._DEFAULT_VECTOR_FIELD
            )
        if self._field_cache:
            if "content" in self._field_cache and "content" not in normalized:
                normalized["content"] = ""
            if "context" in self._field_cache and "context" not in normalized:
                normalized["context"] = ""
        return normalized

    async def upsert(
        self,
        *,
        chunk_id: str,
        kb_id: str,
        material_id: str,
        embedding: list[float],
        content: str | None = None,
        context: str | None = None,
    ) -> None:
        """插入或更新单条向量记录。"""
        upsert = getattr(self._client, "upsert", None)
        if upsert is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 upsert")

        record = {
            "chunk_id": chunk_id,
            "kb_id": kb_id,
            "material_id": material_id,
            "embedding": embedding,
        }
        if content is not None:
            record["content"] = content
        if context is not None:
            record["context"] = context

        normalized = await self._normalize_record(record)
        await upsert(collection_name=self._collection, data=[normalized])

    async def upsert_batch(self, *, records: list[dict]) -> None:
        """批量插入或更新向量记录。"""
        if not records:
            return

        upsert = getattr(self._client, "upsert", None)
        if upsert is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 upsert")

        normalized_records = [await self._normalize_record(r) for r in records]
        await upsert(collection_name=self._collection, data=normalized_records)

    async def delete_by_material(self, material_id: str) -> None:
        """删除指定资料的所有向量记录。"""
        delete = getattr(self._client, "delete", None)
        if delete is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 delete")

        escaped_id = _escape_string(material_id)
        await delete(
            collection_name=self._collection,
            filter=f'material_id == "{escaped_id}"',
        )

    async def delete_by_chunk_ids(self, chunk_ids: list[str]) -> None:
        """按 chunk_id 批量删除向量记录。"""
        delete = getattr(self._client, "delete", None)
        if delete is None:
            raise RuntimeError("pymilvus API 不匹配：缺少 delete")
        if not chunk_ids:
            return

        escaped = [_escape_string(cid) for cid in chunk_ids]
        quoted = ", ".join(f'"{cid}"' for cid in escaped)
        await delete(
            collection_name=self._collection,
            filter=f"chunk_id in [{quoted}]",
        )


@lru_cache
def get_milvus_client() -> MilvusClient:
    """获取 Milvus 客户端单例（进程内复用）。"""
    return MilvusClient()
