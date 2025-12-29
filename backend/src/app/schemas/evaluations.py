"""评测相关 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvaluationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class EvaluationRunCreateRequest(BaseModel):
    """创建评测任务请求。"""

    dataset: dict[str, Any] = Field(..., description="问题集与评分规则")
    config: dict[str, Any] = Field(..., description="范围选择、模式等配置")


class EvaluationRunRead(BaseModel):
    """评测任务响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: EvaluationStatus
    summary: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class EvaluationCaseResult(BaseModel):
    """单题评测结果。"""

    question_id: str
    question: str
    single_agent_run_id: uuid.UUID | None = None
    multi_agent_run_id: uuid.UUID | None = None
    single_agent_answer: str | None = None
    multi_agent_answer: str | None = None
    single_agent_metrics: dict[str, Any] | None = None
    multi_agent_metrics: dict[str, Any] | None = None
    reference_answer: str | None = None


class EvaluationResults(BaseModel):
    """评测结果汇总。"""

    eval_run_id: uuid.UUID
    status: EvaluationStatus
    summary: dict[str, Any] | None = None
    case_results: list[EvaluationCaseResult] = Field(default_factory=list)
