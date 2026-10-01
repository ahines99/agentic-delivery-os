from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WorkRecord(Base):
    __tablename__ = "work_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(300), unique=True)
    repository: Mapped[str] = mapped_column(String(200), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))


class RunRecord(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    work_item_id: Mapped[str] = mapped_column(ForeignKey("work_items.id"), index=True)
    state: Mapped[str] = mapped_column(String(40), default="NEW")
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    spec_digest: Mapped[str] = mapped_column(String(64))
    configuration_digest: Mapped[str] = mapped_column(String(64), default="")
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    budget: Mapped[dict[str, Any]] = mapped_column(JSON)
    reserved_microdollars: Mapped[int] = mapped_column(Integer, default=0)
    spent_microdollars: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class CommandRecord(Base):
    __tablename__ = "commands"
    __table_args__ = (UniqueConstraint("actor", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    actor: Mapped[str] = mapped_column(String(200))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))
    digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="RECEIVED")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(40))


class InboxRecord(Base):
    __tablename__ = "inbox"
    __table_args__ = (
        UniqueConstraint("provider", "integration_id", "delivery_id"),
        UniqueConstraint("provider", "integration_id", "digest"),
        UniqueConstraint("provider", "integration_id", "semantic_key"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30))
    integration_id: Mapped[str] = mapped_column(String(100))
    delivery_id: Mapped[str] = mapped_column(String(200))
    semantic_key: Mapped[str] = mapped_column(String(300))
    digest: Mapped[str] = mapped_column(String(64))
    workflow_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))


class OutboxRecord(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    command_id: Mapped[str] = mapped_column(ForeignKey("commands.id"), unique=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    delivered: Mapped[bool] = mapped_column(default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str] = mapped_column(String(36), default="")
    last_error: Mapped[str] = mapped_column(String(100), default="")


class AuditRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("workflow_id", "sequence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(200))
    previous_state: Mapped[str] = mapped_column(String(40))
    next_state: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    event_digest: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(40))


class UsageRecord(Base):
    __tablename__ = "usage_reservations"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    reserved_microdollars: Mapped[int] = mapped_column(Integer)
    reserved_input_tokens: Mapped[int] = mapped_column(Integer)
    reserved_output_tokens: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    actual_microdollars: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SpecificationRecord(Base):
    __tablename__ = "specifications"
    __table_args__ = (UniqueConstraint("workflow_id", "digest"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))


class PublicationRecord(Base):
    __tablename__ = "publications"
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), primary_key=True)
    repository: Mapped[str] = mapped_column(String(200), index=True)
    number: Mapped[int] = mapped_column(Integer)
    head_sha: Mapped[str] = mapped_column(String(40))
    base_sha: Mapped[str] = mapped_column(String(40))
    manifest_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), default="DRAFT_HANDOFF")
    observed_at: Mapped[str] = mapped_column(String(40), default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON)


class CIHeadRecord(Base):
    __tablename__ = "ci_heads"
    repository_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    head_sha: Mapped[str] = mapped_column(String(40), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_generation: Mapped[int | None] = mapped_column(Integer)
    policy_digest: Mapped[str] = mapped_column(String(64), default="")
    evidence_digest: Mapped[str] = mapped_column(String(64), default="")
    snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    observed_at: Mapped[str] = mapped_column(String(40), default="")
    reconciled_at: Mapped[str] = mapped_column(String(40), default="")
    expires_at: Mapped[str] = mapped_column(String(40), default="")
    invalidation_reason: Mapped[str] = mapped_column(String(80), default="")


class CIObservationRecord(Base):
    __tablename__ = "ci_observations"
    __table_args__ = (Index("ix_ci_observations_repository_head", "repository_id", "head_sha"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    inbox_id: Mapped[str] = mapped_column(ForeignKey("inbox.id"), unique=True)
    repository_id: Mapped[int] = mapped_column(BigInteger)
    head_sha: Mapped[str] = mapped_column(String(40))
    generation: Mapped[int] = mapped_column(Integer)
    observation: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))
