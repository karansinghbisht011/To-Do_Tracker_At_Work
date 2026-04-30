from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import Task
from app.connectors.base import CandidateTask


async def find_existing_task(db: AsyncSession, candidate: CandidateTask) -> Task | None:
    """Look for an existing open task with matching source refs."""
    refs = candidate.source_refs

    result = await db.execute(
        select(Task).where(Task.status != "done")
    )
    tasks = result.scalars().all()

    for task in tasks:
        existing_refs = task.source_refs or {}
        for key, val in refs.items():
            if key in existing_refs and existing_refs[key] == val:
                return task

    return None


async def merge_or_create(db: AsyncSession, candidate: CandidateTask) -> Task:
    """Merge candidate into existing task or create a new one."""
    existing = await find_existing_task(db, candidate)

    if existing:
        overrides = existing.user_overrides or {}

        # Merge source refs
        merged_refs = {**(existing.source_refs or {}), **candidate.source_refs}
        existing.source_refs = merged_refs

        # Update fields only if not user-overridden
        if "summary" not in overrides:
            existing.summary = candidate.summary
        if "action_type" not in overrides:
            existing.action_type = candidate.action_type
        if "stakeholder" not in overrides:
            existing.stakeholder = candidate.stakeholder
        if "urgency_score" not in overrides:
            existing.urgency_score = candidate.urgency_score
            existing.urgency_reason = candidate.urgency_reason
        if "due_date" not in overrides and candidate.due_date:
            # Always use the latest due date
            if existing.due_date is None or candidate.due_date > existing.due_date:
                existing.due_date = candidate.due_date

        await db.flush()
        return existing

    task = Task(
        source=candidate.source,
        summary=candidate.summary,
        action_type=candidate.action_type,
        stakeholder=candidate.stakeholder,
        urgency_score=candidate.urgency_score,
        urgency_reason=candidate.urgency_reason,
        due_date=candidate.due_date,
        source_refs=candidate.source_refs,
        status="open",
        user_overrides={},
    )
    db.add(task)
    await db.flush()
    return task
