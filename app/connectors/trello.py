import os
import json
from datetime import datetime, timezone
from app.connectors.base import SubprocessMCPConnector, CandidateTask

# Trello label colors → urgency scores
_LABEL_URGENCY = {
    "red": 90, "orange": 75, "yellow": 55,
    "green": 30, "blue": 40, "purple": 45,
}

_LABEL_KEYWORDS = {
    "critical": 95, "urgent": 85, "high": 75, "medium": 50, "low": 25,
}


class TrelloConnector(SubprocessMCPConnector):
    """Uses delorenj/mcp-server-trello via npx subprocess."""

    def __init__(self, api_key: str | None = None, token: str | None = None):
        self._api_key = api_key or os.environ.get("TRELLO_API_KEY", "")
        self._token = token or os.environ.get("TRELLO_TOKEN", "")

    def _server_params(self):
        from mcp.client.stdio import StdioServerParameters
        return StdioServerParameters(
            command="npx",
            args=["-y", "mcp-server-trello"],
            env={
                **os.environ,
                "TRELLO_API_KEY": self._api_key,
                "TRELLO_TOKEN": self._token,
            },
        )

    async def fetch_events(self, since: datetime) -> list[dict]:
        result = await self.call_tool("get_my_cards", {"filter": "open"})
        cards = []
        for item in result:
            if hasattr(item, "text"):
                try:
                    data = json.loads(item.text)
                    if isinstance(data, list):
                        cards.extend(data)
                except Exception:
                    pass
        # Filter to cards updated since
        since_ts = since.timestamp()
        return [
            c for c in cards
            if _parse_trello_date(c.get("dateLastActivity", "")) >= since_ts
        ]

    def normalize(self, event: dict) -> list[CandidateTask]:
        name = event.get("name", "")
        card_id = event.get("id", "")
        short_url = event.get("shortUrl", "")

        # Due date
        due_date: datetime | None = None
        raw_due = event.get("due")
        if raw_due:
            try:
                due_date = datetime.fromisoformat(raw_due.replace("Z", "+00:00"))
            except ValueError:
                pass

        # Urgency from labels
        labels = event.get("labels", [])
        urgency_score = 50
        urgency_reason = "Assigned Trello card"
        for label in labels:
            color = (label.get("color") or "").lower()
            label_name = (label.get("name") or "").lower()
            score = _LABEL_KEYWORDS.get(label_name, _LABEL_URGENCY.get(color, 0))
            if score > urgency_score:
                urgency_score = score
                urgency_reason = f"Trello label: {label.get('name', color)}"

        # List name → action type
        list_name = (event.get("list") or {}).get("name", "").lower()
        action_type = _list_to_action(list_name)

        # Stakeholder: last commenter if available, else board name
        members = event.get("idMembers", [])
        board_name = (event.get("board") or {}).get("name", "")
        stakeholder = board_name or (members[0] if members else "")

        return [CandidateTask(
            source="trello",
            summary=name,
            action_type=action_type,
            stakeholder=stakeholder,
            urgency_score=urgency_score,
            urgency_reason=urgency_reason,
            due_date=due_date,
            source_refs={"trello": card_id, "trello_url": short_url},
            raw_payload=event,
        )]


def _list_to_action(list_name: str) -> str:
    if "in progress" in list_name or "doing" in list_name:
        return "Continue task"
    if "review" in list_name:
        return "Review"
    if "blocked" in list_name:
        return "Unblock"
    if "done" in list_name or "complete" in list_name:
        return "Close"
    return "Work"


def _parse_trello_date(date_str: str) -> float:
    if not date_str:
        return 0.0
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
