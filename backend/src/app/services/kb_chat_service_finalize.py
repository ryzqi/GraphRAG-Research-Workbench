from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any


from app.agents.kb_chat_agentic.json_safety import ensure_json_safe
from app.agents.kb_chat_memory import (
    append_kb_chat_memory_entry,
)
from app.core.memory_store import StoreManager
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.evidence import Evidence, EvidenceSourceKind
from app.schemas.chats import (
    AgentRunRead,
    ChatAnswerResponse,
    ChatMessageRead,
    KbChatConfig,
    EvidenceItem,
    EvidenceSourceKind as EvidenceItemSourceKind,
    SemanticCacheMeta,
)
from app.services.evidence_guardrails import (
    enforce_kb_answer_citation_guardrails,
    is_stable_citation_id,
)
from app.services.kb_evidence import stable_citation_sort_key
from app.services.streaming import (
    extract_answer_text,
)

from app.services.kb_chat_service_contracts import _as_str_dict

logger = logging.getLogger(__name__)
async def _finalize_run(
    self,
    *,
    session: ChatSession,
    run: AgentRun,
    kb_chat_config: KbChatConfig,
    started_at: datetime,
    question_vector: list[float] | None = None,
    answer: str,
    final_evidence_items: list[dict[str, Any]] | None = None,
    final_citation_catalog: dict[str, dict[str, Any]] | None = None,
    stage_summaries: dict[str, Any],
    metrics: dict[str, Any],
    status: AgentRunStatus = AgentRunStatus.SUCCEEDED,
    error_message: str | None = None,
    terminal_reason: str | None = None,
    clarification_payload: dict[str, Any] | None = None,
    reflection: dict[str, Any] | None = None,
    query_strategy: str | None = None,
    routing_decisions: dict[str, Any] | None = None,
) -> ChatAnswerResponse:
    # answer 已经剥离思考段（<think>/thinking/reasoning_content）

    # 保存证据（先构建，再对答案做引用约束，避免落库/返回不一致）
    def _parse_uuid(value: object) -> uuid.UUID | None:
        if value is None:
            return None
        try:
            return uuid.UUID(str(value))
        except Exception:
            return None

    evidence_items: list[EvidenceItem] = []
    seen_evidence_chunk_ids: set[uuid.UUID] = set()
    citation_catalog: dict[str, dict[str, Any]] = {}
    citation_id_by_chunk_id: dict[str, str] = {}
    selected_evidence_items = (
        list(final_evidence_items) if isinstance(final_evidence_items, list) else []
    )

    if selected_evidence_items:
        for it in selected_evidence_items:
            if not isinstance(it, dict):
                continue

            chunk_id = _parse_uuid(it.get("chunk_id"))
            if chunk_id and chunk_id in seen_evidence_chunk_ids:
                continue

            source_kind_raw = it.get("source_kind")
            source_kind = (
                EvidenceSourceKind.KB
                if source_kind_raw == "kb"
                else EvidenceSourceKind.EXTERNAL
            )

            kb_id = _parse_uuid(it.get("kb_id"))
            material_id = _parse_uuid(it.get("material_id"))
            if source_kind == EvidenceSourceKind.KB and (
                chunk_id is None or kb_id is None or material_id is None
            ):
                # KB 证据必须能追溯到具体 chunk。
                continue

            excerpt = str(it.get("excerpt") or "")[:500]
            if not excerpt.strip():
                continue
            source_excerpt = self._normalize_optional_text(it.get("source_excerpt"))

            locator = (
                it.get("locator") if isinstance(it.get("locator"), dict) else None
            )
            raw_citation_id = it.get("citation_id")
            citation_id = (
                str(raw_citation_id).strip().upper()
                if isinstance(raw_citation_id, str)
                else ""
            )
            structured_catalog_item = (
                final_citation_catalog.get(citation_id)
                if isinstance(final_citation_catalog, dict) and citation_id
                else None
            )
            if is_stable_citation_id(citation_id):
                citation_catalog[citation_id] = {
                    "citation_id": citation_id,
                    "material_title": self._normalize_optional_text(
                        it.get("material_title")
                        or (
                            structured_catalog_item.get("material_title")
                            if isinstance(structured_catalog_item, dict)
                            else None
                        )
                    ),
                    "citation_title": it.get("citation_title")
                    or (
                        structured_catalog_item.get("citation_title")
                        if isinstance(structured_catalog_item, dict)
                        else None
                    ),
                    "citation_source": it.get("citation_source")
                    or (
                        structured_catalog_item.get("citation_source")
                        if isinstance(structured_catalog_item, dict)
                        else None
                    ),
                    "source_excerpt": self._normalize_optional_text(
                        it.get("source_excerpt")
                        or (
                            structured_catalog_item.get("source_excerpt")
                            if isinstance(structured_catalog_item, dict)
                            else None
                        )
                    ),
                    "locator": locator
                    or (
                        structured_catalog_item.get("locator")
                        if isinstance(structured_catalog_item, dict)
                        else None
                    ),
                    "chunk_id": str(chunk_id) if chunk_id else None,
                    "material_id": str(material_id) if material_id else None,
                    "kb_id": str(kb_id) if kb_id else None,
                }
                if chunk_id:
                    citation_id_by_chunk_id[str(chunk_id)] = citation_id

            self._db.add(
                Evidence(
                    run_id=run.id,
                    source_kind=source_kind,
                    kb_id=kb_id,
                    material_id=material_id,
                    chunk_id=chunk_id,
                    locator=locator,
                    excerpt=excerpt,
                )
            )
            evidence_items.append(
                EvidenceItem(
                    source_kind=EvidenceItemSourceKind(source_kind.value),
                    kb_id=kb_id,
                    material_id=material_id,
                    chunk_id=chunk_id,
                    locator=locator,
                    excerpt=excerpt,
                    source_excerpt=source_excerpt,
                    citation_id=citation_id
                    if is_stable_citation_id(citation_id)
                    else None,
                    citation_title=self._normalize_optional_text(
                        it.get("citation_title")
                    ),
                    citation_source=self._normalize_optional_text(
                        it.get("citation_source")
                    ),
                )
            )
            if chunk_id:
                seen_evidence_chunk_ids.add(chunk_id)

    material_ids: set[uuid.UUID] = set()
    for item in citation_catalog.values():
        material_id = _parse_uuid(item.get("material_id"))
        if material_id:
            material_ids.add(material_id)
    for item in evidence_items:
        if item.material_id is not None:
            material_ids.add(item.material_id)

    material_title_map = await self._load_material_title_map(material_ids)

    citation_meta_by_id: dict[str, dict[str, str | None]] = {}
    ordered_citation_ids = sorted(citation_catalog, key=stable_citation_sort_key)
    for idx, citation_id in enumerate(ordered_citation_ids, 1):
        item = citation_catalog[citation_id]
        material_id_text = self._normalize_optional_text(item.get("material_id"))
        if material_id_text:
            material_title = material_title_map.get(material_id_text)
            if material_title:
                item["material_title"] = material_title

        locator = (
            item.get("locator") if isinstance(item.get("locator"), dict) else None
        )
        if self._extract_locator_material_title(locator):
            item["material_title"] = self._extract_locator_material_title(locator)

        citation_title = self._extract_citation_title(item, fallback_index=idx)
        citation_page_hint = self._extract_citation_page_hint(locator)
        citation_source = self._extract_citation_source(item)
        source_excerpt = self._normalize_optional_text(item.get("source_excerpt"))

        item["citation_title"] = citation_title
        item["citation_page_hint"] = citation_page_hint
        item["citation_source"] = citation_source
        citation_meta_by_id[citation_id] = {
            "citation_title": citation_title,
            "citation_page_hint": citation_page_hint,
            "citation_source": citation_source,
            "source_excerpt": source_excerpt,
        }

    for item in evidence_items:
        raw_citation_id = self._normalize_optional_text(item.citation_id)
        citation_id = raw_citation_id.upper() if raw_citation_id else None
        if not citation_id and item.chunk_id is not None:
            citation_id = citation_id_by_chunk_id.get(str(item.chunk_id))
        if not citation_id:
            continue
        meta = citation_meta_by_id.get(citation_id)
        if meta is None:
            continue
        item.citation_id = citation_id
        item.citation_title = meta.get("citation_title")
        item.citation_page_hint = meta.get("citation_page_hint")
        item.citation_source = meta.get("citation_source")
        item.source_excerpt = meta.get("source_excerpt")

    def _label_from_locator(locator: dict | None) -> str | None:
        if not isinstance(locator, dict):
            return None
        raw = locator.get("citation_label")
        if isinstance(raw, str):
            text = " ".join(raw.replace("[", " ").replace("]", " ").split()).strip()
            if text:
                return text
        filename = locator.get("filename")
        if isinstance(filename, str) and filename.strip():
            base = filename.strip().replace("\\", "/").rsplit("/", 1)[-1]
            stem = base.rsplit(".", 1)[0] if "." in base else base
            normalized = " ".join(stem.replace("[", " ").replace("]", " ").split())
            if normalized:
                return normalized
        return None

    allowed_labels: list[str] = sorted(
        citation_catalog, key=stable_citation_sort_key
    )
    if not allowed_labels:
        seen_labels: set[str] = set()
        for item in evidence_items:
            label = _label_from_locator(
                item.locator if isinstance(item.locator, dict) else None
            )
            if not label:
                continue
            key = label.casefold()
            if key in seen_labels:
                continue
            seen_labels.add(key)
            allowed_labels.append(label)

    # 强约束：引用必须与证据标签一致；无证据（非澄清）时禁止输出看似引用标签。
    allow_no_evidence = terminal_reason == "clarify" or isinstance(
        clarification_payload, dict
    )
    answer = enforce_kb_answer_citation_guardrails(
        answer,
        allowed_labels=allowed_labels,
        allow_no_evidence=allow_no_evidence,
    )
    answer = self._append_citation_sources(
        answer,
        citation_catalog=citation_catalog,
        include_reference_section=False,
    )
    no_evidence_answer = "根据现有资料无法回答该问题（未检索到相关证据）。"
    if (
        not allow_no_evidence
        and len(evidence_items) == 0
        and answer.strip() == no_evidence_answer
    ):
        answer = self._build_no_evidence_response(
            reason_code=terminal_reason,
            stage_summaries=stage_summaries
            if isinstance(stage_summaries, dict)
            else {},
            selected_kb_ids=session.selected_kb_ids,
        )

    # 最佳努力写入一条小型结构化记忆记录（有界且带 TTL）。
    if status == AgentRunStatus.SUCCEEDED and self._settings.memory_enabled:
        try:
            await append_kb_chat_memory_entry(
                store=StoreManager.get_store(),
                user_id=self._resolve_kb_chat_user_id(session),
                thread_id=str(session.id),
                kb_ids=[str(k) for k in (session.selected_kb_ids or [])],
                question=str(run.question or "").strip(),
                answer=extract_answer_text(answer),
                run_id=str(run.id),
                settings=self._settings,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("写入 KB Chat 记忆失败: %s", exc)

    # 保存助手消息
    assistant_msg = ChatMessage(
        session_id=session.id,
        role=MessageRole.ASSISTANT,
        content=answer,
    )
    self._db.add(assistant_msg)
    summary_metrics: dict[str, object] = {}
    if status == AgentRunStatus.SUCCEEDED:
        try:
            summary_result = await self._summary_service.maybe_update_summary(
                session.id
            )
            if summary_result:
                summary_metrics = {
                    "summary_updated": True,
                    **summary_result.stats,
                }
        except Exception as exc:  # pragma: no cover
            logger.warning("摘要更新失败: %s", exc)

    # 更新运行状态
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.final_output = answer
    run.error_message = (
        None if status == AgentRunStatus.SUCCEEDED else (error_message or "")
    )
    finished_at = run.finished_at or datetime.now(timezone.utc)
    latency_ms = int((finished_at - started_at).total_seconds() * 1000)
    route_consistency_rate = self._compute_route_consistency(
        query_strategy=query_strategy,
        routing_decisions=routing_decisions,
    )
    final_state_consistency_rate = self._compute_final_state_consistency(
        routing_decisions=routing_decisions,
        terminal_reason=terminal_reason,
    )
    clarification_consistency_rate = self._compute_clarification_consistency(
        metrics=metrics,
        clarification_payload=clarification_payload,
        terminal_reason=terminal_reason,
    )
    protocol_required_field_drift_rate = float(
        metrics.get("protocol_required_field_drift_rate") or 0.0
    )
    p95_latency_increase_pct = await self._compute_p95_latency_increase_pct(
        current_latency_ms=latency_ms,
    )
    metrics = {
        **metrics,
        "route_consistency_rate": route_consistency_rate,
        "final_state_consistency_rate": final_state_consistency_rate,
        "clarification_consistency_rate": clarification_consistency_rate,
        "p95_latency_increase_pct": p95_latency_increase_pct,
        "protocol_required_field_drift_rate": protocol_required_field_drift_rate,
        "gray_release_indicators": {
            "route_consistency_rate": route_consistency_rate,
            "final_state_consistency_rate": final_state_consistency_rate,
            "clarification_consistency_rate": clarification_consistency_rate,
            "p95_latency_increase_pct": p95_latency_increase_pct,
            "protocol_required_field_drift_rate": protocol_required_field_drift_rate,
        },
    }
    gray_release_gate = self._build_gray_release_gate(metrics)
    gray_release_gate["source_run_id"] = str(run.id)
    gray_release_gate["evaluated_at"] = finished_at.isoformat()
    gray_release_gate["trigger_rollback"] = (
        bool(
            getattr(
                self._settings, "kb_chat_gray_release_auto_rollback_enabled", True
            )
        )
        and gray_release_gate.get("pass") is False
    )
    metrics["gray_release_gate"] = gray_release_gate
    stage_summaries = {**stage_summaries, "gray_release_gate": gray_release_gate}
    self._persist_gray_release_anomaly_sample(
        run_id=run.id,
        gate=gray_release_gate,
        metrics=metrics,
        stage_summaries=stage_summaries,
    )
    stage_summaries = ensure_json_safe(
        stage_summaries, settings=self._settings, label="stage_summaries"
    )
    metrics = ensure_json_safe(metrics, settings=self._settings, label="metrics")
    run.stage_summaries = stage_summaries
    run.metrics = {
        "evidence_count": len(evidence_items),
        "evidence_chunk_ids": [
            str(item.chunk_id)
            for item in evidence_items
            if item.chunk_id is not None
        ],
        "citation_ids": sorted(citation_catalog, key=stable_citation_sort_key),
        "latency_ms": latency_ms,
        **summary_metrics,
        **metrics,
    }

    await self._db.commit()
    await self._db.refresh(assistant_msg)
    await self._db.refresh(run)

    semantic_cache_skip_reason = self._semantic_cache_entry_admission_reason(
        status=status,
        clarification_payload=clarification_payload,
        routing_decisions=routing_decisions,
        reflection=reflection if isinstance(reflection, dict) else None,
        degrade_reason=terminal_reason,
        answer=answer,
        evidence=evidence_items,
        metrics=run.metrics if isinstance(run.metrics, dict) else {},
        stage_summaries=run.stage_summaries
        if isinstance(run.stage_summaries, dict)
        else {},
    )
    if semantic_cache_skip_reason is None:
        try:
            cached_stage_summaries = _as_str_dict(run.stage_summaries)
            cached_metrics = _as_str_dict(run.metrics)
            await self._write_semantic_cache_entry(
                session=session,
                kb_chat_config=kb_chat_config,
                question=str(run.question or "").strip(),
                answer=extract_answer_text(answer),
                evidence=evidence_items,
                stage_summaries=cached_stage_summaries,
                metrics=cached_metrics,
                question_vector=question_vector,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("语义缓存写入失败: %s", exc)

    return ChatAnswerResponse(
        assistant_message=ChatMessageRead.model_validate(assistant_msg),
        evidence=evidence_items,
        source="live",
        cache=SemanticCacheMeta(
            hit=False,
            threshold=self._semantic_cache_threshold(),
            ttl_seconds=self._semantic_cache_ttl_seconds(),
        ),
        stage_summaries=run.stage_summaries
        if isinstance(run.stage_summaries, dict)
        else None,
        metrics=run.metrics if isinstance(run.metrics, dict) else None,
        run=AgentRunRead.model_validate(run),
    )
