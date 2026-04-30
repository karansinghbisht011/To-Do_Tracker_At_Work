import traceback
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

app = FastAPI(title="Gen10x To-Do Board API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://gen10x-todo-tracker.vercel.app", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Helpers defined BEFORE routes ────────────────────────────────────

def _require_api_key(x_api_key: str = Header(...)):
    if x_api_key != get_settings().api_key:
        raise HTTPException(401, "Invalid API key")


def _verify_cron(authorization: str | None):
    if not authorization:
        raise HTTPException(401, "Missing authorization")
    token = authorization.removeprefix("Bearer ").strip()
    if token != get_settings().cron_secret:
        raise HTTPException(401, "Invalid cron secret")


# ── Routers — all mounted under /api so paths match Vercel's routing ─

_import_errors: dict[str, str] = {}

def _try_include(module_path: str, attr: str):
    try:
        mod = __import__(module_path, fromlist=[attr])
        app.include_router(getattr(mod, attr), prefix="/api")
    except Exception:
        _import_errors[module_path] = traceback.format_exc()

_try_include("app.routers.tasks", "router")
_try_include("app.routers.connections", "router")
_try_include("app.routers.webhooks", "router")


# ── Core endpoints ────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "import_errors": list(_import_errors.keys())}


@app.post("/api/refresh")
async def refresh(_: None = Depends(_require_api_key)):
    from app.workers.sync import run_full_sync
    await run_full_sync(lookback_hours=24)
    return {"status": "sync triggered"}


@app.post("/api/cron/sync")
async def cron_sync(authorization: str = Header(None)):
    _verify_cron(authorization)
    from app.workers.sync import run_full_sync
    await run_full_sync(lookback_hours=1)
    return {"status": "ok"}


@app.post("/api/cron/rerank")
async def cron_rerank(authorization: str = Header(None)):
    _verify_cron(authorization)
    from app.db.session import get_session_factory
    from app.pipeline.rank import rerank_open_tasks
    async with get_session_factory()() as db:
        count = await rerank_open_tasks(db)
    return {"status": "ok", "reranked": count}
