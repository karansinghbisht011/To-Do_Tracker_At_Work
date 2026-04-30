from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, Text, JSON, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))          # jira|slack|gmail|trello
    access_token: Mapped[str] = mapped_column(Text)            # encrypted (Fernet)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="connected")  # connected|expired|error
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RawEvent(Base):
    __tablename__ = "raw_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))            # jira|slack|gmail|trello
    payload: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed: Mapped[bool] = mapped_column(Boolean, default=False)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    summary: Mapped[str] = mapped_column(Text)
    action_type: Mapped[str] = mapped_column(String(64))       # Reply|Work|Update|Debug NOW|etc.
    stakeholder: Mapped[str] = mapped_column(String(255), nullable=True)
    urgency_score: Mapped[int] = mapped_column(Integer, default=50)   # 0–100
    urgency_reason: Mapped[str] = mapped_column(Text, nullable=True)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    priority_score: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="open")   # open|snoozed|done
    source_refs: Mapped[dict] = mapped_column(JSON, default=dict)     # {jira:"PROJ-1", slack:"C1/123"}
    user_overrides: Mapped[dict] = mapped_column(JSON, default=dict)  # preserved across re-syncs
    snooze_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=True)    # originating connector
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
