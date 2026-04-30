from datetime import datetime
from app.connectors.base import RemoteMCPConnector, CandidateTask

# Slack messages need LLM extraction — normalize() returns a stub;
# extract.py enriches it with summary, action, urgency, due_date.


class SlackConnector(RemoteMCPConnector):
    mcp_url = "https://mcp.slack.com/mcp"

    async def fetch_events(self, access_token: str, since: datetime) -> list[dict]:
        since_ts = str(since.timestamp())
        result = await self.call_tool(
            "slack_search_public_and_private",
            {
                "query": f"to:me after:{since.strftime('%Y-%m-%d')}",
                "sort": "timestamp",
                "count": 50,
            },
            access_token,
        )
        messages = []
        for item in result:
            if hasattr(item, "text"):
                import json
                try:
                    data = json.loads(item.text)
                    messages.extend(data.get("messages", {}).get("matches", []))
                except Exception:
                    pass
        return messages

    async def fetch_thread(self, channel: str, thread_ts: str, access_token: str) -> list[dict]:
        result = await self.call_tool(
            "slack_read_thread",
            {"channel_id": channel, "thread_ts": thread_ts},
            access_token,
        )
        replies = []
        for item in result:
            if hasattr(item, "text"):
                import json
                try:
                    data = json.loads(item.text)
                    replies.extend(data.get("messages", []))
                except Exception:
                    pass
        return replies

    def normalize(self, event: dict) -> list[CandidateTask]:
        channel = (event.get("channel") or {})
        channel_name = channel.get("name", "") if isinstance(channel, dict) else str(channel)
        user = event.get("username") or event.get("user", "")
        text = event.get("text", "")
        ts = event.get("ts", "")

        due_date: datetime | None = None
        try:
            due_date = datetime.fromtimestamp(float(ts))
        except (ValueError, TypeError):
            pass

        # Stub — extract.py fills in summary, action_type, urgency, refined due_date
        return [CandidateTask(
            source="slack",
            summary=text[:120],
            action_type="Reply",               # default; overridden by LLM
            stakeholder=f"{user} / #{channel_name}" if channel_name else user,
            urgency_score=50,
            urgency_reason=None,               # filled by LLM
            due_date=due_date,
            source_refs={"slack": f"{channel_name}/{ts}"},
            raw_payload=event,
        )]
