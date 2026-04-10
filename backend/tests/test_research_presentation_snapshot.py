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
                "plan_snapshot",
                content_json={
                    "research_brief": "围绕补贴政策和销量趋势做对比研究",
                    "complexity": "simple",
                    "summary": "先收集政策，再比对销量与区域差异。",
                    "subtasks": [
                        {
                            "title": "梳理主要市场补贴政策",
                            "description": "整理中国、欧盟、美国的补贴政策和调整窗口。",
                            "target_sources": ["web"],
                        },
                        {
                            "title": "比对销量与市场份额",
                            "description": "结合销量、份额和区域结构识别政策影响。",
                            "target_sources": ["web", "paper"],
                        },
                    ],
                    "target_sources": ["web", "paper"],
                },
            ),
            _build_artifact(
                "plan_progress_snapshot",
                content_json={
                    "steps": [
                        {
                            "index": 1,
                            "title": "梳理主要市场补贴政策",
                            "description": "整理中国、欧盟、美国的补贴政策和调整窗口。",
                            "target_sources": ["web"],
                            "status": "complete",
                        },
                        {
                            "index": 2,
                            "title": "比对销量与市场份额",
                            "description": "结合销量、份额和区域结构识别政策影响。",
                            "target_sources": ["web", "paper"],
                            "status": "current",
                        },
                    ],
                    "current_step_index": 2,
                    "completed_step_count": 1,
                    "updated_at": "2026-04-10T09:00:00Z",
                },
            ),
            _build_artifact(
                "metrics_snapshot",
                content_json={
                    "quality": {"citation_count": 12},
                },
            )
        ],
    )

    assert snapshot["surface"] == "live"
    assert snapshot["live"]["plan_steps"] == [
        {
            "key": "plan-step-1",
            "label": "梳理主要市场补贴政策",
            "state": "complete",
        },
        {
            "key": "plan-step-2",
            "label": "比对销量与市场份额",
            "state": "current",
        },
    ]
    assert snapshot["live"]["progress"]["current_stage_label"] == "比对销量与市场份额"
    assert snapshot["live"]["progress"]["percent"] == 50


def test_build_research_presentation_snapshot_includes_live_board_agent_and_parallel_tasks() -> None:
    snapshot = build_research_presentation_snapshot(
        session=_build_session(ResearchSessionStatus.RUNNING),
        events=[_build_event(1, "research.runtime.activity")],
        artifacts=[
            _build_artifact(
                "plan_snapshot",
                content_json={
                    "research_brief": "围绕补贴政策和销量趋势做对比研究",
                    "complexity": "simple",
                    "summary": "先收集政策，再比对销量与区域差异。",
                    "subtasks": [
                        {
                            "title": "梳理主要市场补贴政策",
                            "description": "整理中国、欧盟、美国的补贴政策和调整窗口。",
                            "target_sources": ["web"],
                        }
                    ],
                    "target_sources": ["web"],
                },
            ),
            _build_artifact(
                "runtime_live_board_json",
                content_json={
                    "current_agent_label": "web",
                    "current_task_id": "claim-1-web",
                    "current_task_label": "验证 claim 1 的网页证据",
                    "current_task_kind": "claim",
                    "status_message": "web 子代理开始抓取来源",
                    "parallel_tasks": [
                        {
                            "task_id": "claim-1-web",
                            "title": "验证 claim 1 的网页证据",
                            "task_kind": "claim",
                            "status": "started",
                            "agent_label": "web",
                            "parallel_group": "claim-1",
                        }
                    ],
                    "agent_runs": [
                        {
                            "agent_label": "web",
                            "status": "running",
                            "completed_task_count": 0,
                            "active_task_count": 1,
                        }
                    ],
                },
            ),
        ],
    )

    assert snapshot["live"]["current_agent_label"] == "web"
    assert snapshot["live"]["current_task_label"] == "验证 claim 1 的网页证据"
    assert snapshot["live"]["parallel_tasks"][0]["task_id"] == "claim-1-web"
    assert snapshot["live"]["agent_runs"][0]["agent_label"] == "web"


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
    assert snapshot["report"]["summary"] == "生成式 AI 正在重塑半导体供应链。"
    assert "lead" not in snapshot["report"]
    assert "highlights" not in snapshot["report"]
    assert "chart" not in snapshot["report"]
    assert "spotlight_cards" not in snapshot["report"]
    assert "outlook_cards" not in snapshot["report"]
    assert "references" not in snapshot["report"]


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
    assert "lead" not in snapshot["report"]
