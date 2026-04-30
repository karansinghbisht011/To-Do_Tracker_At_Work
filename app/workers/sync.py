from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Connection, RawEvent, Task
from app.db.session import get_session_factory
from app.pipeline.deduplicate import merge_or_create
from app.pipeline.normalize import normalize_events
from app.pipeline.rank import compute_priority_score
from app.routers.connections import decrypt


async def run_full_sync(lookback_hours: int = 24):
    """Run full sync for all connected providers. Called by Vercel Cron."""
    async with get_session_factory()() as db:
        result = await db.execute(
            select(Connection).where(Connection.status == "connected")
        )
        connections = result.scalars().all()

        since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

        for conn in connections:
            try:
                access_token = decrypt(conn.access_token)
                await _sync_provider(db, conn.provider, access_token, since)
            except Exception as e:
                conn.status = "error"
                conn.metadata_ = {**(conn.metadata_ or {}), "last_error": str(e)}

        await db.commit()


async def _sync_provider(
    db: AsyncSession,
    provider: str,
    access_token: str,
    since: datetime,
):
    # Lazy imports — connectors import mcp which must not run at startup
    if provider == "jira":
        from app.connectors.jira import JiraConnector
        connector = JiraConnector()
        events = await connector.fetch_events(access_token, since)
        candidates = await normalize_events("jira", events, connector)

    elif provider == "slack":
        from app.connectors.slack import SlackConnector
        connector = SlackConnector()
        events = await connector.fetch_events(access_token, since)
        candidates = await normalize_events("slack", events, connector)

    elif provider == "gmail":
        from app.connectors.gmail import GmailConnector
        connector = GmailConnector()
        events = await connector.fetch_events(since)
        candidates = await normalize_events("gmail", events, connector)

    elif provider == "trello":
        from app.connectors.trello import TrelloConnector
        connector = TrelloConnector()
        events = await connector.fetch_events(since)
        candidates = await normalize_events("trello", events, connector)

    else:
        return

    for raw_event_data in events:
        raw_event = RawEvent(source=provider, payload=raw_event_data, processed=True)
        db.add(raw_event)

    for candidate in candidates:
        task = await merge_or_create(db, candidate)
        task.priority_score = compute_priority_score(task)

    await db.flush()


async def run_pipeline_for_event(db: AsyncSession, raw_event: RawEvent):
    """Process a single webhook-delivered raw event through the pipeline."""
    source = raw_event.source
    payload = raw_event.payload

    from app.connectors.jira import JiraConnector
    from app.connectors.slack import SlackConnector
    from app.connectors.trello import TrelloConnector
    connector_map = {
        "jira": JiraConnector(),
        "slack": SlackConnector(),
        "trello": TrelloConnector(),
    }
    connector = connector_map.get(source)
    if not connector:
        return

    candidates = await normalize_events(source, [payload], connector)
    for candidate in candidates:
        task = await merge_or_create(db, candidate)
        task.priority_score = compute_priority_score(task)

    raw_event.processed = True
    await db.commit()
