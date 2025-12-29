"""检查点 API 端点。

提供检查点状态查询、历史记录和恢复执行功能。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.checkpoint import CheckpointManager
from app.schemas.checkpoints import (
    CheckpointHistoryItem,
    CheckpointHistoryResponse,
    CheckpointStateResponse,
    ResumeRequest,
    ResumeResponse,
)

router = APIRouter(prefix="/checkpoints", tags=["checkpoints"])


@router.get("/{thread_id}", response_model=CheckpointStateResponse)
async def get_checkpoint(thread_id: str) -> CheckpointStateResponse:
    """获取检查点状态。"""
    checkpoint_tuple = await CheckpointManager.get_state(thread_id)

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail="检查点不存在")

    return CheckpointStateResponse(
        thread_id=thread_id,
        checkpoint_id=checkpoint_tuple.checkpoint.get("id") if checkpoint_tuple.checkpoint else None,
        channel_values=checkpoint_tuple.checkpoint.get("channel_values") if checkpoint_tuple.checkpoint else None,
        created_at=None,
    )


@router.get("/{thread_id}/history", response_model=CheckpointHistoryResponse)
async def list_checkpoint_history(
    thread_id: str,
    limit: int = 10,
) -> CheckpointHistoryResponse:
    """列出检查点历史。"""
    history = await CheckpointManager.list_history(thread_id, limit=limit)

    items = [
        CheckpointHistoryItem(
            checkpoint_id=cp.checkpoint.get("id", "") if cp.checkpoint else "",
            thread_id=thread_id,
            created_at=None,
            metadata=cp.metadata,
        )
        for cp in history
    ]

    return CheckpointHistoryResponse(thread_id=thread_id, history=items)


@router.post("/{thread_id}/resume", response_model=ResumeResponse)
async def resume_execution(
    thread_id: str,
    request: ResumeRequest,
) -> ResumeResponse:
    """从检查点恢复执行（Human-in-the-loop）。

    用于在中断点提供人工输入后继续执行。
    """
    checkpoint_tuple = await CheckpointManager.get_state(thread_id)

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail="检查点不存在")

    # 检查是否处于等待人工输入状态
    # 实际恢复逻辑需要根据具体图实现
    return ResumeResponse(
        thread_id=thread_id,
        status="pending",
        message="恢复请求已接收，需要在具体服务中实现恢复逻辑",
    )


@router.delete("/{thread_id}")
async def delete_checkpoint(thread_id: str) -> dict:
    """删除检查点。"""
    await CheckpointManager.delete_thread(thread_id)
    return {"status": "deleted", "thread_id": thread_id}
