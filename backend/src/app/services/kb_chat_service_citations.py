from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain.messages import AIMessage
from sqlalchemy import select

from app.agents.kb_chat_agentic.json_safety import ensure_json_safe
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.evidence import Evidence, EvidenceSourceKind
from app.models.source_material import SourceMaterial
from app.schemas.chats import (
    AgentRunRead,
    ChatAnswerResponse,
    ChatMessageRead,
    ChatPendingUserClarificationResponse,
    EvidenceItem,
    PendingClarification,
    SemanticCacheMeta,
)
from app.services.evidence_guardrails import (
    extract_citation_labels,
    is_stable_citation_id,
    normalize_citation_label,
)
from app.services.kb_evidence import stable_citation_sort_key
from app.services.semantic_cache.policy import (
    SEMANTIC_CACHE_HIT_TYPE_STRONG as _SEMANTIC_CACHE_HIT_TYPE_STRONG,
)
from app.services.semantic_cache.models import SemanticCacheHit
from app.services.streaming import (
    StreamState,
    extract_answer_text,
)

from app.services.kb_chat_service_contracts import _as_str_dict

logger = logging.getLogger(__name__)
def _normalize_optional_text(self, value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None

def _extract_locator_material_title(self, locator: dict[str, Any] | None) -> str | None:
    if not isinstance(locator, dict):
        return None
    return self._normalize_optional_text(locator.get("material_title"))

def _extract_filename_stem(self, locator: dict[str, Any] | None) -> str | None:
    if not isinstance(locator, dict):
        return None
    filename = locator.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        return None
    base = filename.strip().replace("\\", "/").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    normalized = normalize_citation_label(stem)
    return normalized or None

def _extract_citation_source(self, item: dict[str, Any]) -> str | None:
    direct = self._normalize_optional_text(item.get("citation_source"))
    if direct:
        return direct
    locator = item.get("locator")
    if not isinstance(locator, dict):
        return None
    filename = self._normalize_optional_text(locator.get("filename"))
    if filename:
        return filename
    return self._normalize_optional_text(locator.get("source"))

def _extract_citation_title(self, item: dict[str, Any], *, fallback_index: int) -> str:
    material_title = self._normalize_optional_text(
        item.get("material_title")
    )
    if material_title:
        return material_title

    raw = item.get("citation_title")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()

    locator = item.get("locator")
    if isinstance(locator, dict):
        locator_material_title = self._extract_locator_material_title(
            locator
        )
        if locator_material_title:
            return locator_material_title
        label = locator.get("citation_label")
        if isinstance(label, str):
            normalized = normalize_citation_label(label)
            if normalized:
                return normalized
        filename_stem = self._extract_filename_stem(locator)
        if filename_stem:
            return filename_stem
    return f"资料{fallback_index}"

async def _load_material_title_map(
    self, material_ids: set[uuid.UUID]
) -> dict[str, str]:
    if not material_ids:
        return {}
    stmt = select(SourceMaterial.id, SourceMaterial.title).where(
        SourceMaterial.id.in_(list(material_ids))
    )
    result = await self._db.execute(stmt)
    title_map: dict[str, str] = {}
    for material_id, title in result.all():
        if isinstance(title, str) and title.strip():
            title_map[str(material_id)] = title.strip()
    return title_map

def _extract_citation_page_hint(self, locator: dict[str, Any] | None) -> str | None:
    if not isinstance(locator, dict):
        return None
    page_start = locator.get("page_start")
    page_end = locator.get("page_end")
    if isinstance(page_start, int) and page_start > 0:
        if isinstance(page_end, int) and page_end > 0 and page_end != page_start:
            return f"p.{page_start}-{page_end}"
        return f"p.{page_start}"
    if isinstance(page_end, int) and page_end > 0:
        return f"p.{page_end}"
    return None

def _append_citation_sources(
    cls,
    answer: str,
    *,
    citation_catalog: dict[str, dict[str, Any]] | None,
    include_reference_section: bool = False,
) -> str:
    text = str(answer or "").strip()
    if (
        not include_reference_section
        or not text
        or not isinstance(citation_catalog, dict)
        or not citation_catalog
    ):
        return text

    used = [
        label.strip().upper()
        for label in extract_citation_labels(text)
        if is_stable_citation_id(label)
    ]
    if not used:
        return text

    ordered_ids: list[str] = []
    seen: set[str] = set()
    for citation_id in sorted(set(used), key=stable_citation_sort_key):
        if citation_id in seen:
            continue
        if citation_id not in citation_catalog:
            continue
        seen.add(citation_id)
        ordered_ids.append(citation_id)
    if not ordered_ids:
        return text

    lines = ["参考来源："]
    for idx, citation_id in enumerate(ordered_ids, 1):
        item = citation_catalog[citation_id]
        title = cls._extract_citation_title(item, fallback_index=idx)
        locator = item.get("locator")
        page_hint = cls._extract_citation_page_hint(
            locator if isinstance(locator, dict) else None
        )
        if page_hint:
            lines.append(f"[{citation_id}] {title}（{page_hint}）")
        else:
            lines.append(f"[{citation_id}] {title}")

    return f"{text}\n\n" + "\n".join(lines)

def _extract_last_good_answer(self, 
    *,
    answer: str,
    stream_state: StreamState,
) -> tuple[str | None, str | None]:
    answer_text = extract_answer_text(answer).strip()
    if answer_text:
        return answer_text, "final_answer"

    final_answer = extract_answer_text(stream_state.final_answer).strip()
    if final_answer:
        return final_answer, "stream_state.final_answer"

    draft_answer = extract_answer_text(stream_state.draft_answer).strip()
    if draft_answer:
        return draft_answer, "stream_state.draft_answer"

    for msg in reversed(stream_state.messages):
        if isinstance(msg, AIMessage):
            text = extract_answer_text(msg.content).strip()
            if text:
                return text, "ai_message"

    best_answer = stream_state.best_answer
    if isinstance(best_answer, str) and best_answer.strip():
        return best_answer.strip(), "stream_state.best_answer"

    return None, None

def _clarification_round_count(self, metrics: dict[str, Any] | None) -> int:
    if not isinstance(metrics, dict):
        return 0
    value = metrics.get("clarification_round")
    if isinstance(value, int) and value > 0:
        return value
    return 0

async def _persist_clarification_pending(
    self,
    *,
    session: ChatSession,
    run: AgentRun,
    started_at: datetime,
    message: str,
    pending_clarification: PendingClarification | None,
    stage_summaries: dict[str, Any],
    metrics: dict[str, Any],
) -> ChatPendingUserClarificationResponse:
    now = datetime.now(timezone.utc)
    round_count = (
        self._clarification_round_count(
            run.metrics if isinstance(run.metrics, dict) else None
        )
        + 1
    )
    payload_dict = (
        pending_clarification.model_dump(mode="json")
        if isinstance(pending_clarification, PendingClarification)
        else None
    )
    stage_summaries = {
        **(stage_summaries if isinstance(stage_summaries, dict) else {}),
        "clarification_pending": {
            "pending": True,
            "round": round_count,
            "message": message,
            "pending_clarification": payload_dict,
            "requested_at": now.isoformat(),
        },
    }
    stage_summaries = ensure_json_safe(
        stage_summaries, settings=self._settings, label="stage_summaries"
    )

    metrics = ensure_json_safe(
        metrics if isinstance(metrics, dict) else {},
        settings=self._settings,
        label="metrics",
    )
    run.status = AgentRunStatus.RUNNING
    run.finished_at = None
    run.final_output = None
    run.error_message = None
    run.stage_summaries = stage_summaries
    run.metrics = {
        **metrics,
        "latency_ms": int((now - started_at).total_seconds() * 1000),
        "clarification_pending": True,
        "clarification_round": round_count,
        "ambiguity_triggered": True,
    }

    await self._db.commit()
    await self._db.refresh(run)
    return ChatPendingUserClarificationResponse(
        thread_id=str(session.id),
        message=message,
        pending_clarification=pending_clarification,
        stage_summaries=run.stage_summaries
        if isinstance(run.stage_summaries, dict)
        else None,
        metrics=run.metrics if isinstance(run.metrics, dict) else None,
        run=AgentRunRead.model_validate(run),
    )

async def _persist_semantic_cache_hit(
    self,
    *,
    session: ChatSession,
    user_content: str,
    cache_hit: SemanticCacheHit,
) -> ChatAnswerResponse:
    now = datetime.now(timezone.utc)
    user_msg = ChatMessage(
        session_id=session.id,
        role=MessageRole.USER,
        content=user_content,
    )
    self._db.add(user_msg)
    run = AgentRun(
        id=uuid.uuid4(),
        run_type=AgentRunType.KB_ANSWER,
        session_id=session.id,
        question=user_content,
        selected_kb_ids=session.selected_kb_ids,
        allow_external=session.allow_external,
        mode=session.mode,
        status=AgentRunStatus.SUCCEEDED,
        started_at=now,
        finished_at=now,
        final_output=cache_hit.answer,
        error_message=None,
    )
    self._db.add(run)

    evidence_items: list[EvidenceItem] = []
    for raw_item in cache_hit.evidence:
        if not isinstance(raw_item, dict):
            continue
        try:
            evidence_items.append(EvidenceItem.model_validate(raw_item))
        except Exception:
            continue
    persisted_evidence_items: list[EvidenceItem] = []
    seen_evidence_chunk_ids: set[uuid.UUID] = set()
    for item in evidence_items:
        excerpt = str(item.excerpt or "").strip()
        if not excerpt:
            continue
        source_kind = (
            EvidenceSourceKind.KB
            if str(item.source_kind) == EvidenceSourceKind.KB.value
            else EvidenceSourceKind.EXTERNAL
        )
        if source_kind == EvidenceSourceKind.KB and (
            item.kb_id is None or item.material_id is None or item.chunk_id is None
        ):
            continue
        if item.chunk_id is not None and item.chunk_id in seen_evidence_chunk_ids:
            continue
        self._db.add(
            Evidence(
                run_id=run.id,
                source_kind=source_kind,
                kb_id=item.kb_id,
                material_id=item.material_id,
                chunk_id=item.chunk_id,
                locator=item.locator if isinstance(item.locator, dict) else None,
                excerpt=excerpt[:500],
            )
        )
        persisted_evidence_items.append(item)
        if item.chunk_id is not None:
            seen_evidence_chunk_ids.add(item.chunk_id)

    stage_summaries = {
        **(
            cache_hit.stage_summaries
            if isinstance(cache_hit.stage_summaries, dict)
            else {}
        ),
        "retry_cache": self._build_retry_cache_metrics({}),
        "semantic_cache": {
            "hit": True,
            "score": cache_hit.score,
            "threshold": cache_hit.threshold,
            "ttl_seconds": cache_hit.ttl_seconds,
            "entry_id": cache_hit.entry_id,
            "schema_version": cache_hit.schema_version,
            "hit_type": cache_hit.hit_type or _SEMANTIC_CACHE_HIT_TYPE_STRONG,
            "created_at": cache_hit.created_at,
        },
    }
    metrics = {
        **(cache_hit.metrics if isinstance(cache_hit.metrics, dict) else {}),
        **self._build_retry_cache_metrics({}),
        "semantic_cache": {
            "hit": True,
            "score": cache_hit.score,
            "threshold": cache_hit.threshold,
            "ttl_seconds": cache_hit.ttl_seconds,
            "entry_id": cache_hit.entry_id,
            "schema_version": cache_hit.schema_version,
            "hit_type": cache_hit.hit_type or _SEMANTIC_CACHE_HIT_TYPE_STRONG,
            "created_at": cache_hit.created_at,
            "context_fingerprint": cache_hit.context_fingerprint,
            "kb_version": cache_hit.kb_version,
        },
        "latency_ms": 0,
    }
    stage_summaries, metrics = await self._refresh_semantic_cache_hit_metrics(
        stage_summaries=stage_summaries,
        metrics=metrics,
    )
    gray_release_gate = _as_str_dict(metrics.get("gray_release_gate"))
    finished_at = run.finished_at
    gray_release_gate = {
        **gray_release_gate,
        "source_run_id": str(run.id),
        "evaluated_at": finished_at.isoformat() if finished_at is not None else None,
        "trigger_rollback": (
            bool(
                getattr(
                    self._settings,
                    "kb_chat_gray_release_auto_rollback_enabled",
                    True,
                )
            )
            and gray_release_gate.get("pass") is False
        ),
    }
    metrics["gray_release_gate"] = gray_release_gate
    stage_summaries["gray_release_gate"] = gray_release_gate
    run.stage_summaries = ensure_json_safe(
        stage_summaries,
        settings=self._settings,
        label="stage_summaries",
    )
    run.metrics = ensure_json_safe(
        metrics, settings=self._settings, label="metrics"
    )

    assistant_msg = ChatMessage(
        session_id=session.id,
        role=MessageRole.ASSISTANT,
        content=cache_hit.answer,
    )
    self._db.add(assistant_msg)
    await self._db.commit()
    await self._db.refresh(assistant_msg)
    await self._db.refresh(run)

    return ChatAnswerResponse(
        assistant_message=ChatMessageRead.model_validate(assistant_msg),
        evidence=persisted_evidence_items,
        source="cached",
        cache=SemanticCacheMeta(
            hit=True,
            score=cache_hit.score,
            threshold=cache_hit.threshold,
            ttl_seconds=cache_hit.ttl_seconds,
            entry_id=cache_hit.entry_id,
            schema_version=cache_hit.schema_version,
            hit_type=(
                _SEMANTIC_CACHE_HIT_TYPE_STRONG
                if cache_hit.hit_type == _SEMANTIC_CACHE_HIT_TYPE_STRONG
                or cache_hit.hit_type is None
                else None
            ),
            created_at=cache_hit.created_at,
        ),
        stage_summaries=run.stage_summaries
        if isinstance(run.stage_summaries, dict)
        else None,
        metrics=run.metrics if isinstance(run.metrics, dict) else None,
        run=AgentRunRead.model_validate(run),
    )

def _build_semantic_cache_display_output_items(self, 
    cache_meta: SemanticCacheMeta | None,
) -> list[dict[str, str]]:
    hit_type = cache_meta.hit_type if cache_meta is not None else None
    score = cache_meta.score if cache_meta is not None else None
    threshold = cache_meta.threshold if cache_meta is not None else None
    ttl_seconds = cache_meta.ttl_seconds if cache_meta is not None else None
    return [
        {
            "key": "hit_type",
            "label": "命中类型",
            "value": str(hit_type or _SEMANTIC_CACHE_HIT_TYPE_STRONG),
        },
        {
            "key": "score",
            "label": "命中分数",
            "value": (
                f"{float(score):.2f}"
                if isinstance(score, (int, float))
                else "unknown"
            ),
        },
        {
            "key": "threshold",
            "label": "阈值",
            "value": (
                f"{float(threshold):.2f}"
                if isinstance(threshold, (int, float))
                else "unknown"
            ),
        },
        {
            "key": "ttl_seconds",
            "label": "TTL",
            "value": str(int(ttl_seconds))
            if isinstance(ttl_seconds, (int, float))
            else "unknown",
        },
    ]

def _emit_semantic_cache_fast_path(
    self,
    *,
    run_id: uuid.UUID,
    cache_meta: SemanticCacheMeta | None,
    start_seq: int,
) -> list[tuple[str, dict[str, Any]]]:
    node_name = "semantic_cache"
    node_path = [node_name]
    execution_id = f"semantic-cache:{run_id}"
    step_ts = datetime.now(timezone.utc)
    node_io_ts = datetime.now(timezone.utc)
    step_payload = {
        "execution_id": execution_id,
        "step_id": node_name,
        "label": node_name,
        "status": "started",
        "node": node_name,
        "ts": step_ts.isoformat(),
        "meta": {
            "task_id": execution_id,
            "node_path": node_path,
        },
    }
    return [
        (
            "step",
            self._build_protocol_event_payload(
                event_type="step",
                run_id=run_id,
                payload=step_payload,
                node={"id": node_name, "name": node_name},
                event_id=f"{run_id}:{start_seq}",
                seq=start_seq,
                node_path=node_path,
            ),
        ),
        (
            "node_io",
            self._build_node_io_payload(
                run_id=run_id,
                execution_id=execution_id,
                node_name=node_name,
                node_id=node_name,
                phase="end",
                attempt=1,
                display_output_items=self._build_semantic_cache_display_output_items(
                    cache_meta
                ),
                ts=node_io_ts,
                node_path=node_path,
            ),
        ),
    ]