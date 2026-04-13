"""正文补读。"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.documents import Document

from app.config.policy_loader import load_search_policy

from .contracts import ReadProvider
from .documents import document_url, extract_domain, merge_document_metadata


def _should_enrich(
    document: Document,
    *,
    low_quality_domain_suffixes: Sequence[str],
    snippet_min_length: int,
) -> bool:
    snippet = str(document.page_content or "").strip()
    if len(snippet) < snippet_min_length:
        return True
    domain = str(
        document.metadata.get("domain") or extract_domain(document_url(document)) or ""
    )
    return any(
        domain == suffix or domain.endswith(f".{suffix}")
        for suffix in low_quality_domain_suffixes
    )


async def enrich_documents(
    documents: Sequence[Document],
    *,
    read_provider: ReadProvider | None,
    top_k: int | None = None,
) -> tuple[list[Document], dict[str, object] | None]:
    enrichment_policy = load_search_policy().enrichment
    effective_top_k = (
        int(enrichment_policy.top_k) if top_k is None else max(int(top_k), 0)
    )
    if read_provider is None or effective_top_k <= 0:
        return list(documents), None

    enriched = list(documents)
    candidate_indexes = [
        index
        for index, document in enumerate(enriched)
        if _should_enrich(
            document,
            low_quality_domain_suffixes=enrichment_policy.low_quality_domain_suffixes,
            snippet_min_length=int(enrichment_policy.snippet_min_length),
        )
    ][:effective_top_k]
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
            payload = await read_provider.read(url=url)
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
