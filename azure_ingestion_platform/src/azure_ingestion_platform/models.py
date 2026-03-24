from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="pending_consent", index=True)
    consent_state: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class TenantCredential(Base):
    __tablename__ = "tenant_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    credential_type: Mapped[str] = mapped_column(String(40), index=True)
    client_id: Mapped[str] = mapped_column(String(255), default="")
    secret_encrypted: Mapped[str] = mapped_column(Text, default="")
    secret_fingerprint: Mapped[str] = mapped_column(String(128), default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "credential_type", name="uq_tenant_credentials_type"),)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    state: Mapped[str] = mapped_column(String(80), default="")
    authorization_source: Mapped[str] = mapped_column(String(80), default="")
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("raw_payloads.id"))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "subscription_id", name="uq_tenant_subscription"),)


class RawPayload(Base):
    __tablename__ = "raw_payloads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    subscription_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    endpoint: Mapped[str] = mapped_column(String(255), default="")
    request_url: Mapped[str] = mapped_column(Text, default="")
    continuation_token: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload_hash: Mapped[str] = mapped_column(String(128), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    collector: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    worker_id: Mapped[str] = mapped_column(String(120), default="")
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stats_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_text: Mapped[str] = mapped_column(Text, default="")


class IngestionCheckpoint(Base):
    __tablename__ = "ingestion_checkpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    scope_key: Mapped[str] = mapped_column(String(255), index=True)
    cursor: Mapped[str] = mapped_column(Text, default="")
    watermark: Mapped[str] = mapped_column(String(80), default="")
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "source", "scope_key", name="uq_ingestion_checkpoint_scope"),)


class CollectorSchedule(Base):
    __tablename__ = "collector_schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "source", name="uq_collector_schedule"),)


class ResourceCurrent(Base):
    __tablename__ = "resources_current"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[str] = mapped_column(String(128), index=True)
    resource_id: Mapped[str] = mapped_column(Text, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    resource_type: Mapped[str] = mapped_column(String(255), default="", index=True)
    resource_group: Mapped[str] = mapped_column(String(255), default="", index=True)
    location: Mapped[str] = mapped_column(String(120), default="")
    kind: Mapped[str] = mapped_column(String(120), default="")
    sku: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tags_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    identity_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    managed_by: Mapped[str] = mapped_column(Text, default="")
    properties_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_hash: Mapped[str] = mapped_column(String(128), index=True)
    last_seen_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("raw_payloads.id"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("tenant_id", "subscription_id", "resource_id", name="uq_current_resource"),)


class ResourceHistory(Base):
    __tablename__ = "resources_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[str] = mapped_column(String(128), index=True)
    resource_id: Mapped[str] = mapped_column(Text, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    change_kind: Mapped[str] = mapped_column(String(40), default="snapshot")
    source_hash: Mapped[str] = mapped_column(String(128), index=True)
    properties_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("raw_payloads.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[str] = mapped_column(String(128), index=True)
    event_id: Mapped[str] = mapped_column(String(255), index=True)
    event_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    category: Mapped[str] = mapped_column(String(120), default="")
    operation_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    status: Mapped[str] = mapped_column(String(120), default="")
    caller: Mapped[str] = mapped_column(String(255), default="")
    correlation_id: Mapped[str] = mapped_column(String(255), default="")
    level: Mapped[str] = mapped_column(String(80), default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("raw_payloads.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    __table_args__ = (UniqueConstraint("tenant_id", "subscription_id", "event_id", name="uq_activity_event"),)


class ResourceChange(Base):
    __tablename__ = "resource_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[str] = mapped_column(String(128), index=True)
    resource_id: Mapped[str] = mapped_column(Text, index=True)
    change_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    change_type: Mapped[str] = mapped_column(String(120), default="")
    changed_properties_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("raw_payloads.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))


class MetricPoint(Base):
    __tablename__ = "metric_points"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[str] = mapped_column(String(128), index=True)
    resource_id: Mapped[str] = mapped_column(Text, index=True)
    metric_namespace: Mapped[str] = mapped_column(String(255), default="")
    metric_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    aggregation: Mapped[str] = mapped_column(String(80), default="")
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    average: Mapped[float | None] = mapped_column(Float)
    minimum: Mapped[float | None] = mapped_column(Float)
    maximum: Mapped[float | None] = mapped_column(Float)
    total: Mapped[float | None] = mapped_column(Float)
    count: Mapped[float | None] = mapped_column(Float)
    dimensions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("raw_payloads.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))


class CostUsage(Base):
    __tablename__ = "cost_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[str] = mapped_column(String(128), index=True)
    usage_date: Mapped[str] = mapped_column(String(32), index=True)
    resource_id: Mapped[str] = mapped_column(Text, default="", index=True)
    resource_group: Mapped[str] = mapped_column(String(255), default="")
    service_name: Mapped[str] = mapped_column(String(255), default="")
    meter_category: Mapped[str] = mapped_column(String(255), default="")
    currency: Mapped[str] = mapped_column(String(32), default="USD")
    cost_actual: Mapped[float] = mapped_column(Float, default=0.0)
    cost_amortized: Mapped[float] = mapped_column(Float, default=0.0)
    usage_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    tags_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pricing_model: Mapped[str] = mapped_column(String(120), default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("raw_payloads.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))


class AdvisorRecommendation(Base):
    __tablename__ = "advisor_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[str] = mapped_column(String(128), index=True)
    recommendation_id: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(120), default="")
    impact: Mapped[str] = mapped_column(String(120), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    resource_id: Mapped[str] = mapped_column(Text, default="")
    potential_savings: Mapped[float | None] = mapped_column(Float)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("raw_payloads.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    __table_args__ = (UniqueConstraint("tenant_id", "subscription_id", "recommendation_id", name="uq_advisor_recommendation"),)


class EntraDirectoryAudit(Base):
    __tablename__ = "entra_directory_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    audit_id: Mapped[str] = mapped_column(String(255), index=True)
    activity_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    category: Mapped[str] = mapped_column(String(120), default="")
    activity_display_name: Mapped[str] = mapped_column(String(255), default="")
    initiated_by: Mapped[str] = mapped_column(String(255), default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("raw_payloads.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    __table_args__ = (UniqueConstraint("tenant_id", "audit_id", name="uq_entra_directory_audit"),)


class EntraSignin(Base):
    __tablename__ = "entra_signins"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    signin_id: Mapped[str] = mapped_column(String(255), index=True)
    created_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    user_principal_name: Mapped[str] = mapped_column(String(255), default="")
    app_display_name: Mapped[str] = mapped_column(String(255), default="")
    status_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("raw_payloads.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    __table_args__ = (UniqueConstraint("tenant_id", "signin_id", name="uq_entra_signin"),)
