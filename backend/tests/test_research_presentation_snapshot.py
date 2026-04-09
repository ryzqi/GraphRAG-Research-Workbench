import uuid
from datetime import datetime, timezone

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import ResearchArtifactRead, ResearchEventEnvelope
from app.services.research_presentation_snapshot import build_research_presentation_snapshot


def _build_session(status: ResearchSessionStatus) -> ResearchSession:
    return ResearchSession(
        id=uuid.uuid4(),
        thread_id="thread-1",
        question="2024年全球电动汽车市场分析",
        status=status,
    )


def _build_artifact(
    artifact_key: str,
    *,
    content_text: str | None = None,
    content_json: dict[str, object] | list[object] | None = None,
) -> ResearchArtifactRead:
    return ResearchArtifactRead(
        artifact_key=artifact_key,
        content_text=content_text,
        content_json=content_json,
        citations=[],
    )


def _build_event(
    *,
    session_id: uuid.UUID,
    sequence: int,
    event_type: str,
    phase: str,
    payload: dict[str, object] | None = None,
) -> ResearchEventEnvelope:
    return ResearchEventEnvelope(
        event_id=f"evt-{sequence}",
        sequence=sequence,
        timestamp=datetime(2026, 4, 9, 12, 0, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        session_id=session_id,
        phase=phase,
        namespace="main",
        payload=payload or {},
    )


def test_builds_clarifying_presentation_snapshot() -> None:
    session = _build_session(ResearchSessionStatus.CLARIFYING)
    artifacts = [
        _build_artifact(
            "clarification_request",
            content_json={
                "summary": "为了生成更精确的报告，需要先补齐研究边界。",
                "questions": [
                    {
                        "id": "region",
                        "question": "更关注哪些地区？",
                        "why_it_matters": "地区范围会直接改变样本和政策比较维度。",
                    },
                    {
                        "id": "policy",
                        "question": "是否重点关注补贴政策？",
                        "why_it_matters": "这会影响研究重点和指标选择。",
                    },
                ],
            },
        )
    ]

    snapshot = build_research_presentation_snapshot(
        session=session,
        events=[],
        artifacts=artifacts,
    )

    assert snapshot["surface"] == "clarifying"
    assert snapshot["hero"]["title"] == "2024年全球电动汽车市场分析"
    assert snapshot["rail"]["steps"][0]["key"] == "clarify"
    assert snapshot["rail"]["steps"][0]["state"] == "current"
    assert snapshot["clarification"]["summary"] == "为了生成更精确的报告，需要先补齐研究边界。"
    assert len(snapshot["clarification"]["question_cards"]) == 2
    assert snapshot["clarification"]["question_cards"][0]["title"] == "更关注哪些地区？"


def test_builds_planning_presentation_snapshot() -> None:
    session = _build_session(ResearchSessionStatus.PLAN_READY)
    artifacts = [
        _build_artifact(
            "plan_snapshot",
            content_json={
                "research_brief": "聚焦欧洲与中国新能源汽车市场竞争格局。",
                "complexity": "comparative",
                "summary": "比较主要市场、政策补贴和代表企业走势。",
                "target_sources": ["web", "paper"],
                "subtasks": [
                    {
                        "title": "收集市场规模与销量数据",
                        "description": "整理 2024 年主要地区销量、渗透率和增长率。",
                        "target_sources": ["web"],
                    },
                    {
                        "title": "分析重点企业竞争格局",
                        "description": "对比比亚迪、特斯拉及欧洲本土车企的市场表现。",
                        "target_sources": ["web", "paper"],
                    },
                ],
            },
        )
    ]

    snapshot = build_research_presentation_snapshot(
        session=session,
        events=[],
        artifacts=artifacts,
    )

    assert snapshot["surface"] == "planning"
    assert snapshot["rail"]["steps"][1]["key"] == "plan"
    assert snapshot["rail"]["steps"][1]["state"] == "current"
    assert snapshot["plan"]["summary"] == "比较主要市场、政策补贴和代表企业走势。"
    assert len(snapshot["plan"]["steps"]) == 2
    assert snapshot["plan"]["steps"][0]["index"] == 1
    assert snapshot["plan"]["primary_action"]["label"] == "开始研究"


def test_builds_live_presentation_snapshot_from_status_and_events() -> None:
    session = _build_session(ResearchSessionStatus.RUNNING)
    events = [
        _build_event(
            session_id=session.id,
            sequence=1,
            event_type="research.run.started",
            phase="runtime",
            payload={"lc_agent_name": "deep-research"},
        ),
        _build_event(
            session_id=session.id,
            sequence=2,
            event_type="research.trace.recorded",
            phase="runtime",
            payload={"lc_agent_name": "web-search", "source_provider": "searxng"},
        ),
    ]
    artifacts = [
        _build_artifact(
            "metrics_snapshot",
            content_json={
                "quality": {
                    "citation_count": 12,
                    "finding_count": 3,
                },
                "coverage": {
                    "pass": True,
                },
            },
        )
    ]

    snapshot = build_research_presentation_snapshot(
        session=session,
        events=events,
        artifacts=artifacts,
    )

    assert snapshot["surface"] == "live"
    assert snapshot["rail"]["steps"][2]["key"] == "run"
    assert snapshot["rail"]["steps"][2]["state"] == "current"
    assert snapshot["live"]["progress"]["current_stage_label"] == "执行研究"
    assert snapshot["live"]["progress"]["percent"] >= 55
    assert len(snapshot["live"]["activity"]) == 2
    assert snapshot["live"]["activity"][0]["event_type"] == "research.trace.recorded"


def test_builds_final_presentation_snapshot_with_outline_and_metric_cards() -> None:
    session = _build_session(ResearchSessionStatus.FINAL)
    artifacts = [
        _build_artifact(
            "report_md",
            content_text="# 研究报告\n\n## 市场概况\n内容 A\n\n## 关键参与者\n内容 B\n\n## 技术演进\n内容 C\n",
        ),
        _build_artifact(
            "report_json",
            content_json={
                "summary": "全球电动汽车市场继续增长，但区域分化明显。",
                "findings": ["中国市场保持高增速", "欧洲补贴退坡影响需求", "供应链成本仍在波动"],
            },
        ),
        _build_artifact(
            "metrics_snapshot",
            content_json={
                "quality": {
                    "citation_count": 12,
                    "finding_count": 3,
                },
                "coverage": {
                    "pass": True,
                },
                "cost": {
                    "session_cost_usd": 0.18,
                },
            },
        ),
        _build_artifact(
            "gate_snapshot",
            content_json={
                "pass": True,
            },
        ),
    ]

    snapshot = build_research_presentation_snapshot(
        session=session,
        events=[],
        artifacts=artifacts,
    )

    assert snapshot["surface"] == "final"
    assert snapshot["rail"]["steps"][3]["key"] == "report"
    assert snapshot["rail"]["steps"][3]["state"] == "current"
    assert [item["title"] for item in snapshot["report"]["outline"]] == [
        "市场概况",
        "关键参与者",
        "技术演进",
    ]
    labels = {item["label"]: item["value"] for item in snapshot["report"]["metric_cards"]}
    assert labels["引用数"] == "12"
    assert labels["关键发现"] == "3"
    assert labels["覆盖状态"] == "通过"
