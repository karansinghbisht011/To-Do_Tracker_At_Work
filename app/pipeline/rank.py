from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import Task

_STAKEHOLDER_WEIGHTS = {
    "ceo": 20, "cto": 20, "vp": 18, "director": 15,
    "manager": 12, "lead": 10,
}


def compute_priority_score(task: Task) -> int:
    score = 0
    now = datetime.now(timezone.utc)

    # Due date component: 0–40 pts (closer = higher)
    if task.due_date:
        due = task.due_date if task.due_date.tzinfo else task.due_date.replace(tzinfo=timezone.utc)
        hours_left = (due - now).total_seconds() / 3600
        if hours_left < 0:
            score += 40                          # overdue
        elif hours_left < 24:
            score += 35
        elif hours_left < 72:
            score += 25
        elif hours_left < 168:                   # 1 week
            score += 15
        else:
            score += max(0, 10 - int(hours_left / 48))

    # Urgency component: 0–30 pts
    score += int((task.urgency_score or 50) * 0.30)

    # Stakeholder importance: 0–20 pts
    stakeholder_lower = (task.stakeholder or "").lower()
    for keyword, weight in _STAKEHOLDER_WEIGHTS.items():
        if keyword in stakeholder_lower:
            score += weight
            break

    # Recency: 0–5 pts (updated in last 24h)
    if task.updated_at:
        updated = task.updated_at if task.updated_at.tzinfo else task.updated_at.replace(tzinfo=timezone.utc)
        hours_since = (now - updated).total_seconds() / 3600
        score += max(0, 5 - int(hours_since / 5))

    return min(score, 100)


async def rerank_open_tasks(db: AsyncSession) -> int:
    """Re-score all open tasks. Returns count of tasks updated."""
    result = await db.execute(select(Task).where(Task.status == "open"))
    tasks = result.scalars().all()

    for task in tasks:
        task.priority_score = compute_priority_score(task)

    await db.commit()
    return len(tasks)
