from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TenantOnboardingRequest(BaseModel):
    slug: str
    display_name: str
    tenant_external_id: str = Field(..., description="Microsoft Entra tenant ID")


class TenantCredentialRequest(BaseModel):
    credential_type: Literal["client_secret"]
    client_id: str
    client_secret: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TenantResponse(BaseModel):
    id: str
    tenant_external_id: str
    slug: str
    display_name: str
    status: str
    onboarded_at: datetime | None = None
    created_at: datetime


class OnboardingResponse(BaseModel):
    tenant: TenantResponse
    consent_url: str


class CollectorSourceResponse(BaseModel):
    source: str
    kind: str
    default_interval_minutes: int
    implemented: bool
    description: str


class RunEnqueueRequest(BaseModel):
    source: str
    subscription_ids: list[str] = Field(default_factory=list)


class IngestionRunResponse(BaseModel):
    id: str
    tenant_id: str
    source: str
    collector: str
    status: str
    scheduled_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt_count: int
    retry_count: int
    error_text: str = ""
    stats_json: dict[str, Any] = Field(default_factory=dict)


class CollectorStatusResponse(BaseModel):
    tenant_id: str
    source: str
    enabled: bool
    interval_minutes: int
    last_run_status: str | None = None
    last_finished_at: datetime | None = None
    lag_seconds: int | None = None
    pending_runs: int = 0


class ResourceRowResponse(BaseModel):
    tenant_id: str
    subscription_id: str
    resource_id: str
    name: str
    resource_type: str
    resource_group: str
    location: str
    is_deleted: bool
    last_seen_at: datetime


class ActivityEventResponse(BaseModel):
    tenant_id: str
    subscription_id: str
    event_id: str
    operation_name: str
    category: str
    status: str
    caller: str
    event_timestamp: datetime | None = None


class RawPayloadResponse(BaseModel):
    id: str
    tenant_id: str
    source: str
    subscription_id: str
    endpoint: str
    request_url: str
    continuation_token: str
    payload_json: dict[str, Any]
    payload_hash: str
    received_at: datetime


class HealthResponse(BaseModel):
    status: str
    database_url: str
