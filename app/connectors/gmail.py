import os
import json
from datetime import datetime
from app.connectors.base import SubprocessMCPConnector, CandidateTask


class GmailConnector(SubprocessMCPConnector):
    """Uses GongRzhe/Gmail-MCP-Server via npx subprocess."""

    def __init__(self, credentials_path: str | None = None):
        self._credentials_path = credentials_path or os.environ.get("GOOGLE_CREDENTIALS_PATH", "")

    def _server_params(self):
        from mcp.client.stdio import StdioServerParameters
        env = {**os.environ}
        if self._credentials_path:
            env["GOOGLE_CREDENTIALS_PATH"] = self._credentials_path
        return StdioServerParameters(
            command="npx",
            args=["-y", "@gongrzhe/server-gmail-autoauth-mcp"],
            env=env,
        )

    async def fetch_events(self, since: datetime) -> list[dict]:
        since_str = since.strftime("%Y/%m/%d")
        result = await self.call_tool(
            "search_emails",
            {"query": f"in:inbox is:unread after:{since_str}", "maxResults": 30},
        )
        threads = []
        for item in result:
            if hasattr(item, "text"):
                try:
                    data = json.loads(item.text)
                    threads.extend(data.get("messages", []) or data.get("threads", []))
                except Exception:
                    pass
        return threads

    async def fetch_thread_detail(self, thread_id: str) -> dict:
        result = await self.call_tool("get_thread", {"threadId": thread_id})
        for item in result:
            if hasattr(item, "text"):
                try:
                    return json.loads(item.text)
                except Exception:
                    pass
        return {}

    def normalize(self, event: dict) -> list[CandidateTask]:
        subject = event.get("subject", event.get("snippet", ""))
        sender = event.get("from", event.get("sender", ""))
        date_str = event.get("date", "")
        thread_id = event.get("threadId", event.get("id", ""))

        due_date: datetime | None = None
        if date_str:
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%SZ"):
                try:
                    due_date = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    pass

        # Rule-based urgency check
        urgency_score = 50
        urgency_reason = "Unread email"
        subject_lower = subject.lower()
        if any(w in subject_lower for w in ["urgent", "asap", "immediate", "critical", "action required"]):
            urgency_score = 85
            urgency_reason = "Urgent keyword in subject"

        # Stub — extract.py fills in summary, action_type, refined urgency, due_date
        return [CandidateTask(
            source="gmail",
            summary=subject[:120],
            action_type="Reply",
            stakeholder=sender,
            urgency_score=urgency_score,
            urgency_reason=urgency_reason,
            due_date=due_date,
            source_refs={"gmail": thread_id},
            raw_payload=event,
        )]
