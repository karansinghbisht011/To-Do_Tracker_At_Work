import httpx
from datetime import datetime, timezone
from urllib.parse import urlencode

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Connection
from app.db.session import get_db
from app.routers.auth import require_api_key

router = APIRouter(prefix="/connect", tags=["connections"])


class ConnectionOut(BaseModel):
    id: int
    provider: str
    status: str
    expires_at: datetime | None

    class Config:
        from_attributes = True


def _fernet() -> Fernet:
    return Fernet(get_settings().encryption_key.encode())


def encrypt(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


@router.get("", response_model=list[ConnectionOut])
async def list_connections(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
):
    result = await db.execute(select(Connection))
    return result.scalars().all()


@router.delete("/{provider}")
async def revoke_connection(
    provider: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
):
    result = await db.execute(select(Connection).where(Connection.provider == provider))
    conn = result.scalar_one_or_none()
    if conn:
        await db.delete(conn)
        await db.commit()
    return {"status": "revoked"}


# ── Atlassian (Jira + Trello) ─────────────────────────────────────────────────

@router.get("/jira/start")
async def jira_oauth_start():
    settings = get_settings()
    params = urlencode({
        "audience": "api.atlassian.com",
        "client_id": settings.atlassian_client_id,
        "scope": "read:jira-work read:jira-user offline_access",
        "redirect_uri": settings.atlassian_redirect_uri,
        "response_type": "code",
        "prompt": "consent",
    })
    return RedirectResponse(f"https://auth.atlassian.com/authorize?{params}")


@router.get("/jira/callback")
async def jira_oauth_callback(code: str, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://auth.atlassian.com/oauth/token", json={
            "grant_type": "authorization_code",
            "client_id": settings.atlassian_client_id,
            "client_secret": settings.atlassian_client_secret,
            "code": code,
            "redirect_uri": settings.atlassian_redirect_uri,
        })
        resp.raise_for_status()
        data = resp.json()

    await _upsert_connection(db, "jira", data["access_token"],
                             data.get("refresh_token"), data.get("expires_in"))
    return RedirectResponse(f"{settings.base_url}?connected=jira")


# ── Google (Gmail) ────────────────────────────────────────────────────────────

@router.get("/gmail/start")
async def gmail_oauth_start():
    settings = get_settings()
    params = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/gmail.readonly",
        "access_type": "offline",
        "prompt": "consent",
    })
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@router.get("/gmail/callback")
async def gmail_oauth_callback(code: str, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data={
            "grant_type": "authorization_code",
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "redirect_uri": settings.google_redirect_uri,
        })
        resp.raise_for_status()
        data = resp.json()

    await _upsert_connection(db, "gmail", data["access_token"],
                             data.get("refresh_token"), data.get("expires_in"))
    return RedirectResponse(f"{settings.base_url}?connected=gmail")


# ── Slack ─────────────────────────────────────────────────────────────────────

@router.get("/slack/start")
async def slack_oauth_start():
    settings = get_settings()
    params = urlencode({
        "client_id": settings.slack_client_id,
        "scope": "channels:history,im:history,search:read,users:read",
        "redirect_uri": settings.slack_redirect_uri,
    })
    return RedirectResponse(f"https://slack.com/oauth/v2/authorize?{params}")


@router.get("/slack/callback")
async def slack_oauth_callback(code: str, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://slack.com/api/oauth.v2.access", data={
            "client_id": settings.slack_client_id,
            "client_secret": settings.slack_client_secret,
            "code": code,
            "redirect_uri": settings.slack_redirect_uri,
        })
        data = resp.json()
        if not data.get("ok"):
            raise HTTPException(400, detail=data.get("error", "Slack OAuth failed"))

    token = data["access_token"]
    await _upsert_connection(db, "slack", token, None, None)
    return RedirectResponse(f"{settings.base_url}?connected=slack")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _upsert_connection(
    db: AsyncSession,
    provider: str,
    access_token: str,
    refresh_token: str | None,
    expires_in: int | None,
):
    result = await db.execute(select(Connection).where(Connection.provider == provider))
    conn = result.scalar_one_or_none()

    expires_at = None
    if expires_in:
        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    if conn:
        conn.access_token = encrypt(access_token)
        if refresh_token:
            conn.refresh_token = encrypt(refresh_token)
        conn.expires_at = expires_at
        conn.status = "connected"
    else:
        conn = Connection(
            provider=provider,
            access_token=encrypt(access_token),
            refresh_token=encrypt(refresh_token) if refresh_token else None,
            expires_at=expires_at,
            status="connected",
        )
        db.add(conn)

    await db.commit()
