from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task
from app.db.session import get_db
from app.pipeline.rank import compute_priority_score
from app.routers.auth import require_api_key

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskOut(BaseModel):
    id: int
    summary: str
    action_type: str
    stakeholder: str | None
    urgency_score: int
    urgency_reason: str | None
    due_date: datetime | None
    priority_score: int
    status: str
    source_refs: dict
    source: str | None
    updated_at: datetime

    class Config:
        from_attributes = True


class SnoozeIn(BaseModel):
    until: datetime


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    status: str = Query("open", pattern="^(open|snoozed|done|all)$"),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
):
    q = select(Task)
    if status != "all":
        q = q.where(Task.status == status)
    q = q.order_by(Task.priority_score.desc())
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/{task_id}/done", response_model=TaskOut)
async def mark_done(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
):
    task = await _get_or_404(db, task_id)
    task.status = "done"
    await db.commit()
    await db.refresh(task)
    return task


@router.post("/{task_id}/snooze", response_model=TaskOut)
async def snooze_task(
    task_id: int,
    body: SnoozeIn,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
):
    task = await _get_or_404(db, task_id)
    task.status = "snoozed"
    task.snooze_until = body.until
    await db.commit()
    await db.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskOut)
async def override_task(
    task_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
):
    """Allow user to override urgency, due_date, or action_type. Preserved across re-syncs."""
    task = await _get_or_404(db, task_id)
    overrides = task.user_overrides or {}
    allowed = {"urgency_score", "due_date", "action_type", "summary"}
    for key, val in body.items():
        if key in allowed:
            setattr(task, key, val)
            overrides[key] = val
    task.user_overrides = overrides
    task.priority_score = compute_priority_score(task)
    await db.commit()
    await db.refresh(task)
    return task


async def _get_or_404(db: AsyncSession, task_id: int) -> Task:
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
