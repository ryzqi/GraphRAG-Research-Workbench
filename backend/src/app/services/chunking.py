"""文本分块策略实现。"""

from __future__ import annotations

import logging
import math

from app.core.settings import Settings, get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.utils.token_counter import count_tokens_approximately

logger = logging.getLogger(__name__)

_SENTENCE_DELIMS = set("。！？!?")


class TextChunker:
    """统一分块入口。"""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedding: EmbeddingClient | None = None,
    ) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._embedding = embedding

    async def split(self, text: str) -> list[str]:
        if not text:
            return []

        strategy = self._settings.ingestion_chunk_strategy
        if strategy == "max_min_semantic":
            return await self._split_semantic(text)
        if strategy != "sliding_window":
            logger.warning("未知分块策略，回退滑动窗口", extra={"strategy": strategy})
        return self._split_sliding_window(text)

    def _split_sliding_window(self, text: str) -> list[str]:
        chunk_size = self._settings.ingestion_chunk_size
        chunk_overlap = self._settings.ingestion_chunk_overlap

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk.strip())
            start = end - chunk_overlap if end < len(text) else end

        return chunks

    async def _split_semantic(self, text: str) -> list[str]:
        sentences = _split_sentences(text)
        if not sentences:
            return []

        embedding = self._embedding or EmbeddingClient()
        self._embedding = embedding

        try:
            vectors = await embedding.embed(texts=sentences)
        except Exception as exc:
            logger.warning("语义分块 embedding 失败，回退滑动窗口", extra={"error": str(exc)})
            return self._split_sliding_window(text)

        min_tokens = max(self._settings.ingestion_semantic_min_tokens, 1)
        max_tokens = max(self._settings.ingestion_semantic_max_tokens, min_tokens)
        threshold = self._settings.ingestion_semantic_similarity_threshold
        overlap_chars = max(self._settings.ingestion_chunk_overlap, 0)

        chunks: list[str] = []
        current = sentences[0]
        current_tokens = count_tokens_approximately(current)

        for idx in range(1, len(sentences)):
            sentence = sentences[idx]
            sentence_tokens = count_tokens_approximately(sentence)
            sim = _cosine_similarity(vectors[idx - 1], vectors[idx])

            if current_tokens + sentence_tokens > max_tokens:
                chunks.append(current.strip())
                current = _apply_overlap(chunks[-1], sentence, overlap_chars)
                current_tokens = count_tokens_approximately(current)
                continue

            if sim < threshold and current_tokens >= min_tokens:
                chunks.append(current.strip())
                current = _apply_overlap(chunks[-1], sentence, overlap_chars)
                current_tokens = count_tokens_approximately(current)
                continue

            current = _merge_text(current, sentence)
            current_tokens += sentence_tokens

        if current.strip():
            chunks.append(current.strip())

        return chunks


def _split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    buf: list[str] = []
    for ch in text:
        buf.append(ch)
        if ch in _SENTENCE_DELIMS or ch == "\n":
            sentence = "".join(buf).strip()
            if sentence:
                sentences.append(sentence)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        sentences.append(tail)
    return sentences


def _merge_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if left.endswith(("\n", " ", "\t")) or right.startswith(("\n", " ", "\t")):
        return f"{left}{right}"
    return f"{left}\n{right}"


def _apply_overlap(previous: str, next_text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0 or not previous:
        return next_text
    tail = previous[-overlap_chars:]
    return _merge_text(tail, next_text)


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
