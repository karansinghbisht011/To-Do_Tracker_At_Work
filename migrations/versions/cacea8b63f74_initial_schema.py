"""initial schema

Revision ID: cacea8b63f74
Revises: 
Create Date: 2026-04-29 16:10:40.462819

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "cacea8b63f74"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("access_token", sa.Text, nullable=False),
        sa.Column("refresh_token", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, nullable=True, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="connected"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_connections_provider", "connections", ["provider"], unique=True)

    op.create_table(
        "raw_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("processed", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_raw_events_processed", "raw_events", ["processed"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("stakeholder", sa.String(255), nullable=True),
        sa.Column("urgency_score", sa.Integer, nullable=False, server_default="50"),
        sa.Column("urgency_reason", sa.Text, nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("priority_score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("source_refs", JSONB, nullable=True, server_default="{}"),
        sa.Column("user_overrides", JSONB, nullable=True, server_default="{}"),
        sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_priority_score", "tasks", ["priority_score"])


def downgrade() -> None:
    op.drop_index("ix_tasks_priority_score", "tasks")
    op.drop_index("ix_tasks_status", "tasks")
    op.drop_table("tasks")
    op.drop_index("ix_raw_events_processed", "raw_events")
    op.drop_table("raw_events")
    op.drop_index("ix_connections_provider", "connections")
    op.drop_table("connections")
