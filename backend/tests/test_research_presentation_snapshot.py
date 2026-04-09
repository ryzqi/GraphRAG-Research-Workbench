from __future__ import annotations

import uuid

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import ResearchArtifactRead, ResearchEventEnvelope
from app.services.research_presentation_snapshot import build_research_presentation_snapshot


def _build_session(status: ResearchSessionStatus) -> ResearchSession:
    session = ResearchSession(
        id=uuid.uuid4(),
        thread_id=f"thread-{uuid.uuid4()}",
        question="2024年全球人工智能半导体行业深度分析",
        status=status,
    )
    session.events = []
    session.artifacts = []
    session.task_outbox_entries = []
    return session


def _build_artifact(
    artifact_key: str,
    *,
    content_text: str | None = None,
    content_json: dict | list | None = None,
) -> ResearchArtifactRead:
    return ResearchArtifactRead(
        artifact_key=artifact_key,
        content_text=content_text,
        content_json=content_json,
        citations=[],
    )


def _build_event(sequence: int, event_type: str) -> ResearchEventEnvelope:
    return ResearchEventEnvelope(
        event_id=f"evt-{sequence}",
        sequence=sequence,
        timestamp=f"2026-04-09T12:00:0{sequence}Z",
        event_type=event_type,
        session_id=uuid.uuid4(),
        phase="runtime",
        namespace="main",
        payload={},
    )


def test_build_research_presentation_snapshot_adds_live_pipeline_steps() -> None:
    snapshot = build_research_presentation_snapshot(
        session=_build_session(ResearchSessionStatus.RUNNING),
        events=[_build_event(1, "research.run.started")],
        artifacts=[
            _build_artifact(
                "metrics_snapshot",
                content_json={
                    "quality": {"citation_count": 12},
                },
            )
        ],
    )

    assert snapshot["surface"] == "live"
    assert snapshot["live"]["pipeline_steps"] == [
        {"key": "collect", "label": "数据收集", "state": "complete"},
        {"key": "extract", "label": "特征提取", "state": "complete"},
        {"key": "model", "label": "语义建模", "state": "current"},
        {"key": "report", "label": "结论生成", "state": "pending"},
    ]


def test_build_research_presentation_snapshot_adds_structured_report_blocks() -> None:
    snapshot = build_research_presentation_snapshot(
        session=_build_session(ResearchSessionStatus.FINAL),
        events=[],
        artifacts=[
            _build_artifact(
                "report_json",
                content_json={
                    "summary": "生成式 AI 正在重塑半导体供应链。",
                    "findings": [
                        "NVIDIA 仍保持生态主导优势。",
                        "AMD 在云侧增量订单中份额提升。",
                        "先进封装成为供给瓶颈。",
                        "HBM 需求继续抬升。",
                    ],
                    "provider_counts": {"GPU": 68, "HBM": 52, "先进封装": 31},
                    "citations": [
                        {"title": "IEA 半导体与算力追踪报告 2024", "origin_url": "https://example.com/iea"},
                        {"title": "Gartner Top Strategic Technology Trends for 2024", "origin_url": "https://example.com/gartner"},
                    ],
                },
            ),
            _build_artifact(
                "report_md",
                content_text="# 研究报告\n\n## 市场概况\n内容 A",
            ),
            _build_artifact(
                "metrics_snapshot",
                content_json={
                    "quality": {"citation_count": 12, "finding_count": 4},
                    "coverage": {"pass": True},
                },
            ),
            _build_artifact(
                "gate_snapshot",
                content_json={"pass": True},
            ),
            _build_artifact(
                "source_ledger_json",
                content_json=[
                    {"provider": "NVIDIA", "title": "Blackwell 周期与 CUDA 生态", "origin_url": "https://example.com/nvidia"},
                    {"provider": "AMD", "title": "MI300 系列与云侧增量订单", "origin_url": "https://example.com/amd"},
                ],
            ),
        ],
    )

    assert snapshot["surface"] == "final"
    assert snapshot["report"]["badge_label"] == "已生成研究报告"
    assert snapshot["report"]["lead"] == "生成式 AI 正在重塑半导体供应链。"
    assert snapshot["report"]["chart"]["title"] == "研究覆盖概览"
    assert snapshot["report"]["chart"]["bars"][0]["label"] == "GPU"
    assert snapshot["report"]["spotlight_cards"][0]["eyebrow"] == "NVIDIA"
    assert snapshot["report"]["outlook_cards"][0]["title"] == "研究启示 01"
    assert snapshot["report"]["references"][0].startswith("01.")


def test_build_research_presentation_snapshot_ignores_extra_runtime_context_fields() -> None:
    snapshot = build_research_presentation_snapshot(
        session=_build_session(ResearchSessionStatus.FINAL),
        events=[],
        artifacts=[
            _build_artifact(
                "report_json",
                content_json={
                    "summary": "执行摘要",
                    "findings": ["Claim A", "Claim B"],
                    "sections": [{"title": "核心结论", "content": "Claim A"}],
                    "metadata": {"confidence_level": "partial"},
                    "runtime_context": {
                        "executive_summary": "Claim A 得到部分支持"
                    },
                },
            ),
            _build_artifact(
                "report_md",
                content_text="# 研究报告\n\n## 核心结论\nClaim A",
            ),
        ],
    )

    assert snapshot["report"]["summary"] == "执行摘要"
    assert snapshot["report"]["lead"] == "执行摘要"
