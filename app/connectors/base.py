from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class CandidateTask:
    source: str
    summary: str
    action_type: str
    stakeholder: str | None = None
    urgency_score: int = 50
    urgency_reason: str | None = None
    due_date: datetime | None = None
    source_refs: dict = field(default_factory=dict)
    raw_payload: dict = field(default_factory=dict)


class RemoteMCPConnector(ABC):
    """Connects to a remote HTTP MCP endpoint (Jira, Slack)."""

    mcp_url: str

    def _auth_headers(self, access_token: str) -> dict:
        return {"Authorization": f"Bearer {access_token}"}

    async def call_tool(self, tool_name: str, args: dict, access_token: str) -> Any:
        # Lazy import so startup doesn't fail if mcp is unavailable
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(
            self.mcp_url,
            headers=self._auth_headers(access_token),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                return result.content

    @abstractmethod
    async def fetch_events(self, access_token: str, since: datetime) -> list[dict]: ...

    @abstractmethod
    def normalize(self, event: dict) -> list[CandidateTask]: ...


class SubprocessMCPConnector(ABC):
    """Spawns a local MCP server subprocess (Gmail, Trello)."""

    async def call_tool(self, tool_name: str, args: dict) -> Any:
        # Lazy import so startup doesn't fail if mcp is unavailable
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters

        params = self._server_params()
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                return result.content

    @abstractmethod
    def _server_params(self) -> Any:
        """Return StdioServerParameters for the subprocess."""

    @abstractmethod
    async def fetch_events(self, since: datetime) -> list[dict]: ...

    @abstractmethod
    def normalize(self, event: dict) -> list[CandidateTask]: ...
