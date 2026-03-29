"""正文补读。"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.documents import Document

from .contracts import ReadProvider
from .documents import document_url, extract_domain, merge_document_metadata

_LOW_QUALITY_DOMAIN_SUFFIXES = (
    "linkedin.com",
    "x.com",
    "twitter.com",
    "medium.com",
)
_SNIPPET_MIN_LENGTH = 180


def _should_enrich(document: Document) -> bool:
    snippet = str(document.page_content or "").strip()
    if len(snippet) < _SNIPPET_MIN_LENGTH:
        return True
    domain = str(document.metadata.get("domain") or extract_domain(document_url(document)) or "")
    return any(domain == suffix or domain.endswith(f".{suffix}") for suffix in _LOW_QUALITY_DOMAIN_SUFFIXES)


async def enrich_documents(
    documents: Sequence[Document],
    *,
    read_provider: ReadProvider | None,
    top_k: int = 2,
    timeout_seconds: float | None = None,
) -> tuple[list[Document], dict[str, object] | None]:
    if read_provider is None or top_k <= 0:
        return list(documents), None

    enriched = list(documents)
    candidate_indexes = [index for index, document in enumerate(enriched) if _should_enrich(document)][:top_k]
    if not candidate_indexes:
        return enriched, {
            "provider": getattr(read_provider, "provider_name", "jina_reader"),
            "ok": True,
            "result_count": 0,
            "elapsed_ms": 0,
            "error": None,
        }

    success_count = 0
    error_messages: list[str] = []
    for index in candidate_indexes:
        url = document_url(enriched[index])
        try:
            payload = await read_provider.read(url=url, timeout_seconds=timeout_seconds)
        except Exception as exc:
            error_messages.append(f"{url}: {exc}")
            continue
        if not isinstance(payload, dict) or payload.get("error"):
            if isinstance(payload, dict) and payload.get("error"):
                error_messages.append(str(payload.get("error")))
            continue
        title = str(payload.get("title") or "").strip() or None
        content = str(payload.get("content") or "").strip()
        if not content:
            continue
        success_count += 1
        enriched[index] = merge_document_metadata(
            enriched[index],
            title=title or enriched[index].metadata.get("title"),
            enriched=True,
        )
        enriched[index] = Document(
            page_content=content,
            metadata=dict(enriched[index].metadata),
        )

    return enriched, {
        "provider": getattr(read_provider, "provider_name", "jina_reader"),
        "ok": success_count > 0,
        "result_count": success_count,
        "elapsed_ms": 0,
        "error": "; ".join(error_messages) if error_messages else None,
    }
