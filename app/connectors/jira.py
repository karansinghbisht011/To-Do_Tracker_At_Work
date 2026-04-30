from datetime import datetime, timezone
from app.connectors.base import RemoteMCPConnector, CandidateTask

# Priority label → urgency score mapping
_PRIORITY_SCORES = {
    "critical": 95, "highest": 90, "high": 75,
    "medium": 50, "low": 25, "lowest": 10,
}


class JiraConnector(RemoteMCPConnector):
    mcp_url = "https://mcp.atlassian.com/v1/mcp"

    async def fetch_events(self, access_token: str, since: datetime) -> list[dict]:
        since_str = since.strftime("%Y-%m-%d")
        result = await self.call_tool(
            "searchJiraIssuesUsingJql",
            {
                "jql": f"assignee = currentUser() AND updated >= '{since_str}' ORDER BY updated DESC",
                "fields": ["summary", "status", "priority", "duedate", "reporter",
                           "comment", "assignee", "labels"],
                "maxResults": 50,
            },
            access_token,
        )
        issues = []
        for item in result:
            if hasattr(item, "text"):
                import json
                try:
                    data = json.loads(item.text)
                    issues.extend(data.get("issues", []))
                except Exception:
                    pass
        return issues

    def normalize(self, event: dict) -> list[CandidateTask]:
        fields = event.get("fields", {})
        issue_key = event.get("key", "")

        summary = fields.get("summary", "")
        status = (fields.get("status") or {}).get("name", "")
        priority_name = ((fields.get("priority") or {}).get("name") or "medium").lower()
        urgency_score = _PRIORITY_SCORES.get(priority_name, 50)

        reporter = fields.get("reporter") or {}
        stakeholder = reporter.get("displayName") or reporter.get("emailAddress", "")

        # Latest date: duedate vs most recent comment timestamp
        due_date: datetime | None = None
        raw_due = fields.get("duedate")
        if raw_due:
            try:
                due_date = datetime.fromisoformat(raw_due).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        comments = (fields.get("comment") or {}).get("comments", [])
        if comments:
            latest_comment = max(comments, key=lambda c: c.get("updated", ""))
            comment_dt_str = latest_comment.get("updated", "")
            if comment_dt_str:
                try:
                    comment_dt = datetime.fromisoformat(comment_dt_str.replace("Z", "+00:00"))
                    # Use comment date only if it's newer than due date (date pushed)
                    if due_date is None or comment_dt > due_date:
                        # Only override if comment explicitly mentions a new date (handled by LLM in extract)
                        pass
                    stakeholder = (latest_comment.get("author") or {}).get("displayName", stakeholder)
                except ValueError:
                    pass

        action_type = _infer_action_type(status, comments)
        urgency_reason = f"Jira priority: {priority_name.title()}"

        return [CandidateTask(
            source="jira",
            summary=summary,
            action_type=action_type,
            stakeholder=stakeholder,
            urgency_score=urgency_score,
            urgency_reason=urgency_reason,
            due_date=due_date,
            source_refs={"jira": issue_key},
            raw_payload=event,
        )]


def _infer_action_type(status: str, comments: list[dict]) -> str:
    status_lower = status.lower()
    if "in progress" in status_lower:
        return "Continue task"
    if "review" in status_lower or "pr" in status_lower:
        return "Review"
    if "blocked" in status_lower:
        return "Unblock"
    if comments:
        last_body = (comments[-1].get("body") or "").lower()
        if "?" in last_body:
            return "Comment back"
        if "update" in last_body:
            return "Update"
    return "Work"
