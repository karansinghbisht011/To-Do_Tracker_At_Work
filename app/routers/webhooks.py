import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.config import get_settings
from app.db.models import RawEvent
from app.db.session import get_db
from app.workers.sync import run_pipeline_for_event

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/jira")
async def jira_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    payload = await request.json()
    event = RawEvent(source="jira", payload=payload)
    db.add(event)
    await db.commit()
    await db.refresh(event)
    await run_pipeline_for_event(db, event)
    return {"status": "ok"}


@router.post("/trello")
async def trello_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    payload = await request.json()
    event = RawEvent(source="trello", payload=payload)
    db.add(event)
    await db.commit()
    await db.refresh(event)
    await run_pipeline_for_event(db, event)
    return {"status": "ok"}


@router.post("/slack")
async def slack_webhook(
    request: Request,
    x_slack_signature: str = Header(None),
    x_slack_request_timestamp: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    body_bytes = await request.body()
    _verify_slack_signature(body_bytes, x_slack_signature, x_slack_request_timestamp)

    payload = json.loads(body_bytes)

    # Respond to Slack URL verification challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload["challenge"]}

    event = RawEvent(source="slack", payload=payload)
    db.add(event)
    await db.commit()
    await db.refresh(event)
    await run_pipeline_for_event(db, event)
    return {"status": "ok"}


def _verify_slack_signature(body: bytes, signature: str | None, timestamp: str | None):
    if not signature or not timestamp:
        raise HTTPException(400, "Missing Slack signature headers")

    # Reject requests older than 5 minutes
    if abs(time.time() - int(timestamp)) > 300:
        raise HTTPException(400, "Request timestamp too old")

    settings = get_settings()
    sig_base = f"v0:{timestamp}:{body.decode()}"
    mac = hmac.new(settings.slack_signing_secret.encode(), sig_base.encode(), hashlib.sha256)
    expected = "v0=" + mac.hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Invalid Slack signature")
