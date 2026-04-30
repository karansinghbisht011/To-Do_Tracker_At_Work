import json
from datetime import datetime
from anthropic import AsyncAnthropic
from app.connectors.base import CandidateTask
from app.config import get_settings

_EXTRACT_TOOL = {
    "name": "extract_task",
    "description": "Extract structured task fields from a message or ticket.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Clear, concise title of what needs to be done (max 100 chars)",
            },
            "action_type": {
                "type": "string",
                "enum": ["Reply", "Comment back", "Update", "Continue task",
                         "Review", "Debug NOW", "Send document", "Schedule call",
                         "Unblock team", "Close ticket", "Work"],
                "description": "The specific next action required",
            },
            "stakeholder": {
                "type": "string",
                "description": "Person/team/channel this task relates to",
            },
            "urgency": {
                "type": "string",
                "enum": ["High", "Medium", "Low"],
                "description": "Urgency level inferred from tone, deadlines, language",
            },
            "urgency_reason": {
                "type": "string",
                "description": "One sentence explaining why this urgency level was assigned",
            },
            "due_date": {
                "type": "string",
                "description": "ISO 8601 date/datetime if extractable, or null. "
                               "Infer from explicit dates OR phrases like 'end of week', "
                               "'ASAP', 'by Thursday'. Always pick the LATEST date if multiple exist.",
                "nullable": True,
            },
        },
        "required": ["summary", "action_type", "stakeholder", "urgency", "urgency_reason"],
    },
}

_URGENCY_SCORES = {"High": 80, "Medium": 50, "Low": 20}

_SYSTEM_PROMPT = """You extract actionable task details from messages.
Be concise. Infer intent from tone and context.
For due dates: extract explicit dates OR infer from phrases like "by EOD", "end of week", "ASAP" (treat as today), "pushing to Nov 10".
Always return the LATEST due date if multiple are mentioned."""


async def enrich_with_llm(task: CandidateTask) -> CandidateTask:
    """Use Claude to extract/refine fields for unstructured sources (Slack, Gmail)."""
    if task.source not in ("slack", "gmail"):
        return task

    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    payload = task.raw_payload
    if task.source == "slack":
        content = f"Slack message from {task.stakeholder}:\n\n{payload.get('text', '')}"
        if payload.get("attachments"):
            content += f"\n\nAttachments: {json.dumps(payload['attachments'])[:500]}"
    else:
        subject = payload.get("subject", "")
        body = payload.get("body", payload.get("snippet", ""))
        sender = payload.get("from", "")
        content = f"Gmail from {sender}\nSubject: {subject}\n\n{body[:1500]}"

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        tools=[_EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_task"},
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_task":
            inp = block.input
            task.summary = inp.get("summary", task.summary)
            task.action_type = inp.get("action_type", task.action_type)
            task.stakeholder = inp.get("stakeholder", task.stakeholder)
            urgency_label = inp.get("urgency", "Medium")
            task.urgency_score = _URGENCY_SCORES.get(urgency_label, 50)
            task.urgency_reason = inp.get("urgency_reason", task.urgency_reason)
            raw_date = inp.get("due_date")
            if raw_date:
                try:
                    parsed = datetime.fromisoformat(raw_date)
                    # Take the latest date between LLM-extracted and existing
                    if task.due_date is None or parsed > task.due_date:
                        task.due_date = parsed
                except ValueError:
                    pass
            break

    return task


async def enrich_trello_comments(task: CandidateTask) -> CandidateTask:
    """Extract due date updates from Trello comments using LLM."""
    comments = task.raw_payload.get("comments", [])
    if not comments:
        return task

    comment_text = "\n".join(
        f"[{c.get('date', '')}] {(c.get('data') or {}).get('text', '')}"
        for c in comments[-5:]  # last 5 comments
    )

    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Trello card: {task.summary}\n\nRecent comments:\n{comment_text}",
        }],
        tools=[_EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_task"},
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_task":
            inp = block.input
            task.action_type = inp.get("action_type", task.action_type)
            raw_date = inp.get("due_date")
            if raw_date:
                try:
                    parsed = datetime.fromisoformat(raw_date)
                    if task.due_date is None or parsed > task.due_date:
                        task.due_date = parsed
                except ValueError:
                    pass
            break

    return task
