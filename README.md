# Gen10x To-Do Tracker — BLR-TEC-07

## Problem Statement

As an engineering manager or senior IC, critical tasks arrive from multiple channels simultaneously — Jira tickets, Slack messages, Gmail threads, Trello cards — each with its own urgency signals, due dates, and stakeholders. Context-switching between four tools to manually assess what to work on next is costly: important items get missed, urgency is misjudged, and prioritization becomes reactive rather than deliberate.

There is no single view that consolidates all of this and tells you **what to do right now, and why**.

---

## Solution

A unified personal to-do dashboard that:

1. **Ingests tasks** from Jira, Slack, Gmail, and Trello via MCP (Model Context Protocol) connectors
2. **Extracts structure** from raw events — title, due date, stakeholder, urgency, recommended action — using rule-based parsing where fields are explicit (Jira/Trello) and Claude AI where they are implicit (Slack messages, Gmail threads)
3. **Scores and ranks** every task on a 0–100 priority scale combining deadline proximity, urgency signals, stakeholder weight, and recency
4. **Serves a single clean UI** — a prioritized table showing what to do, when, and why — with Done/Snooze actions and auto-refresh every 60 seconds

---

## High-Level Design

### System Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                              │
│   Jira Issues   Slack Messages   Gmail Threads   Trello Cards    │
└──────┬──────────────┬───────────────┬──────────────┬────────────┘
       │              │               │              │
       │         MCP (Model Context Protocol)        │
       │    [Official protocol for AI tool access]   │
       ▼              ▼               ▼              ▼
┌──────────────────────────────────────────────────────────────────┐
│                     MCP CONNECTORS                               │
│  Jira/Slack: Remote HTTP MCP servers (hosted by Atlassian/Slack) │
│  Gmail/Trello: Subprocess MCP servers (npx, runs locally/lambda) │
└─────────────────────────┬────────────────────────────────────────┘
                          │  raw events (JSON)
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                   PROCESSING PIPELINE                            │
│                                                                  │
│  1. NORMALIZE   — map raw fields to standard CandidateTask shape │
│                   (rules for Jira/Trello, LLM for Slack/Gmail)   │
│                                                                  │
│  2. EXTRACT     — Claude claude-sonnet-4-6 with tool_use         │
│                   extracts: summary, action, stakeholder,        │
│                   urgency (0-100 + reason), due_date             │
│                   (picks LATEST date signal across thread)       │
│                                                                  │
│  3. DEDUPLICATE — match by source_refs (Jira ID, Trello card ID) │
│                   merge into existing task or create new one     │
│                   always preserve user's manual overrides        │
│                                                                  │
│  4. RANK        — compute priority score (0–100)                 │
│                   due proximity (40) + urgency (30) +            │
│                   stakeholder weight (20) + recency (5) +        │
│                   blocking others bonus (+5)                     │
└─────────────────────────┬────────────────────────────────────────┘
                          │  ranked Task rows
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                     NEON POSTGRES                                │
│   connections  |  raw_events  |  tasks                           │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│               FASTAPI REST API (Vercel Serverless)               │
│   GET /api/tasks → sorted by priority_score DESC                 │
│   POST /api/tasks/{id}/done|snooze                               │
│   POST /api/connect/{provider}/start  → OAuth redirect           │
│   GET  /api/connect/{provider}/callback → store tokens           │
│   POST /api/cron/sync → triggered by Vercel Cron (daily)         │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                     FRONTEND (index.html)                        │
│   Static HTML/JS — fetches /api/tasks on load + every 60s       │
│   Renders priority-sorted table: Task | Due | Stakeholder |      │
│   Urgency | Action | Done/Snooze buttons                         │
│   Connect buttons → trigger OAuth flow per provider              │
└──────────────────────────────────────────────────────────────────┘
```

### Sync Triggers (How data flows in)

| Trigger | When | What happens |
|---|---|---|
| **Vercel Cron** | Daily at 8am | Full sync: all connected providers, last 1 hour of events |
| **Cron rerank** | Daily at 9am | Re-scores open tasks as due dates approach |
| **Webhook** (Jira/Slack/Trello) | Real-time on event | Single event runs through pipeline immediately |
| **Manual refresh** | User clicks Refresh | Full sync across all providers, last 24 hours |

### Field Extraction Logic (per source)

| Field | Jira | Trello | Slack / Gmail |
|---|---|---|---|
| **Task title** | `fields.summary` | `card.name` | LLM-inferred action summary |
| **Due date** | `fields.duedate` OR latest comment date | `card.due` OR latest comment | LLM-extracted; picks LATEST signal across thread |
| **Stakeholder** | `fields.reporter.displayName` | Card creator / last commenter | Sender (incoming) or primary recipient (outgoing) |
| **Urgency** | Priority label (Critical=95, High=75…) | Label color (red=90, orange=75…) | LLM-inferred from tone, "ASAP", deadlines, @here |
| **Action** | Inferred from Jira status | Inferred from list name | LLM: Reply / Schedule call / Unblock team / etc. |

---

## Tech Stack

| Layer | Choice |
|---|---|
| API runtime | Python 3.11 + FastAPI + Mangum (ASGI adapter for Vercel) |
| MCP Client | `mcp` Python SDK — streamable-HTTP (Jira/Slack) + stdio (Gmail/Trello) |
| Database | SQLAlchemy 2.0 async + asyncpg + Neon Postgres (serverless) |
| LLM extraction | Claude API `claude-sonnet-4-6` via `tool_use` for structured output |
| Token storage | Fernet symmetric encryption (AES-128-CBC + HMAC) |
| Scheduler | Vercel Cron Jobs |
| Frontend | Vanilla HTML + JS (no framework needed for a personal tool) |
| Hosting | Vercel — static frontend + Python serverless functions |

---

## Deployment Architecture

```
Vercel Project: gen10x-todo-tracker
├── / → index.html        (static, @vercel/static build)
└── /api/* → api/index.py (Python serverless, @vercel/python build)
                └── Mangum(FastAPI app)
                    ├── /api/tasks*
                    ├── /api/connect*
                    ├── /api/webhooks*
                    └── /api/cron*

Neon Postgres (Vercel Marketplace)
└── gen10x DB
    ├── connections  (OAuth tokens, encrypted)
    ├── raw_events   (raw MCP payloads, JSONB)
    └── tasks        (deduplicated + ranked, JSONB fields)
```

---

## Project Structure

```
Gen10x_BLR-TEC-07 To Do Tracker/
├── api/
│   └── index.py              # Vercel entry: handler = Mangum(app)
├── app/
│   ├── main.py               # FastAPI app init, router mounting, cron + health endpoints
│   ├── config.py             # All env vars via pydantic-settings
│   ├── db/
│   │   ├── models.py         # ORM models: Connection, RawEvent, Task
│   │   └── session.py        # Async engine + session factory
│   ├── connectors/
│   │   ├── base.py           # CandidateTask dataclass, RemoteMCP + SubprocessMCP base classes
│   │   ├── jira.py           # Atlassian remote MCP (JQL search)
│   │   ├── slack.py          # Slack remote MCP (mentions + DMs)
│   │   ├── gmail.py          # Gmail subprocess MCP (npx)
│   │   └── trello.py         # Trello subprocess MCP (npx)
│   ├── pipeline/
│   │   ├── normalize.py      # MCP response → CandidateTask
│   │   ├── extract.py        # Claude tool_use for Slack/Gmail
│   │   ├── deduplicate.py    # source_refs matching + merge logic
│   │   └── rank.py           # Priority score formula + cron rerank
│   ├── routers/
│   │   ├── tasks.py          # Task CRUD + done/snooze
│   │   ├── connections.py    # OAuth start/callback/list/revoke
│   │   └── webhooks.py       # Jira, Slack, Trello webhook receivers
│   └── workers/
│       └── sync.py           # run_full_sync() + run_pipeline_for_event()
├── migrations/               # Alembic — initial schema (all 3 tables + indexes)
├── index.html                # Frontend: dynamic task table + connect buttons
├── Gen10x-To Do Tracker-Static.html  # Original static prototype (8 hardcoded tasks)
├── vercel.json               # Build config, routing rules, cron schedule
├── requirements.txt
└── .env.example
```

---

## Priority Scoring Formula

```
score = due_date_proximity  (0–40 pts)  → closes in <6h = 40pts, decreases over time
      + urgency              (0–30 pts)  → urgency_score × 0.30
      + stakeholder_weight   (0–20 pts)  → based on stakeholder importance
      + recency              (0–5 pts)   → how recently the event was updated
      + waiting_on_user      (+5 pts)    → task is blocking someone else
      ─────────────────────────────────
      max 100
```

---

## Environment Variables

```bash
# Core — required
DATABASE_URL              # Neon Postgres connection string
ANTHROPIC_API_KEY         # Claude API key
API_KEY                   # Endpoint protection (X-API-Key header)
ENCRYPTION_KEY            # Fernet key — generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CRON_SECRET               # Vercel Cron auth token

# OAuth app credentials — requires platform admin approval
ATLASSIAN_CLIENT_ID       # Jira (covers Jira + Confluence OAuth)
ATLASSIAN_CLIENT_SECRET
GOOGLE_CLIENT_ID          # Gmail
GOOGLE_CLIENT_SECRET
SLACK_CLIENT_ID
SLACK_CLIENT_SECRET
SLACK_SIGNING_SECRET

# Trello — API key auth (no OAuth needed for personal use)
TRELLO_API_KEY
TRELLO_TOKEN
```

---

## Current Status

### What's Working
- Vercel deployment live at `gen10x-todo-tracker.vercel.app`
- `/api/health` → `{"status":"ok","import_errors":[]}` — backend fully operational
- Neon Postgres migrated — all 3 tables with indexes in place
- Full pipeline implemented: normalize → extract → deduplicate → rank
- Frontend wired: dynamic task loading, connect buttons, Done/Snooze actions, 60s auto-refresh
- Core env vars set in Vercel: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `API_KEY`, `ENCRYPTION_KEY`, `CRON_SECRET`

### What's Pending

#### Blocked: OAuth App Approvals
Each platform connector requires a registered OAuth application. In enterprise workspaces (Atlassian, Google Workspace, Slack Enterprise) this needs admin approval before credentials can be issued.

| Provider | What's needed | Status |
|---|---|---|
| **Jira** | Atlassian OAuth app → get `ATLASSIAN_CLIENT_ID` + `SECRET` | Pending admin approval |
| **Gmail** | Google Cloud OAuth app (restricted scope: `gmail.readonly`) → get `GOOGLE_CLIENT_ID` + `SECRET` | Pending admin approval |
| **Slack** | Slack app with `channels:history`, `im:read`, `search:read` scopes → get `SLACK_CLIENT_ID` + `SECRET` + `SIGNING_SECRET` | Pending admin approval |
| **Trello** | Generate personal API key + token at `trello.com/app-key` — **no admin needed** | Can be done anytime |

#### Once OAuth Apps Are Approved

1. Set the 7 missing env vars in Vercel dashboard (Settings → Environment Variables)
2. Register webhooks:
   - **Jira**: Webhook auto-registers via API when user connects (implemented in `connections.py`)
   - **Slack**: Enable Events API in Slack app dashboard, point to `https://gen10x-todo-tracker.vercel.app/api/webhooks/slack`
   - **Trello**: Webhook auto-registers per board on connect (implemented)
3. End-to-end test:
   - Connect Jira → assign an issue to yourself → verify it appears in UI within 30 seconds
   - Connect Slack → get a DM mentioning a deadline → verify task appears with correct due date
   - Connect Gmail → send yourself an email with "ASAP" → verify urgency score is high
   - Connect Trello → move a card to "In Progress" → verify action type shows "Continue task"
4. Tune the stakeholder weight function in `pipeline/rank.py` (currently a stub returning 10 for all)

#### Nice-to-Have (post-MVP)
- Token refresh logic for expired OAuth access tokens (Jira/Gmail/Slack all issue short-lived tokens)
- Redis (Upstash) caching layer for `/api/tasks` to avoid DB hit on every frontend refresh
- Cron upgrade to every 15 minutes (requires Vercel Pro plan — Hobby only allows daily)
- More granular snooze UX (snooze until tomorrow morning, end of week, etc.)
- Stakeholder importance config (let user tag "CEO", "direct report", etc. to tune weights)
