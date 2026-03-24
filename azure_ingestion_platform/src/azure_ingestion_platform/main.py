from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .collectors.registry import build_registry
from .config import settings
from .deps import get_db
from .models import ActivityEvent, CollectorSchedule, IngestionRun, RawPayload, ResourceCurrent, Tenant
from .schemas import (
    ActivityEventResponse,
    CollectorSourceResponse,
    CollectorStatusResponse,
    HealthResponse,
    IngestionRunResponse,
    OnboardingResponse,
    RawPayloadResponse,
    ResourceRowResponse,
    RunEnqueueRequest,
    TenantCredentialRequest,
    TenantOnboardingRequest,
    TenantResponse,
)
from .services.jobs import enqueue_run
from .services.tenants import build_onboarding_response, complete_admin_consent, create_tenant, upsert_tenant_credential

app = FastAPI(title="Azure Ingestion Platform", version="0.1.0")
registry = build_registry()


def _tenant_to_response(tenant: Tenant) -> TenantResponse:
    return TenantResponse(
        id=tenant.id,
        tenant_external_id=tenant.tenant_external_id,
        slug=tenant.slug,
        display_name=tenant.display_name,
        status=tenant.status,
        onboarded_at=tenant.onboarded_at,
        created_at=tenant.created_at,
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    scheme = settings.database_url.split("://", 1)[0]
    return HealthResponse(status="ok", database_url=f"{scheme}://...")


@app.get("/api/v1/collector-sources", response_model=list[CollectorSourceResponse])
def list_collector_sources() -> list[CollectorSourceResponse]:
    return [
        CollectorSourceResponse(
            source=collector.source,
            kind=collector.kind,
            default_interval_minutes=collector.default_interval_minutes(),
            implemented=collector.implemented,
            description=collector.description,
        )
        for collector in registry.values()
    ]


@app.post("/api/v1/tenants/onboarding", response_model=OnboardingResponse)
def start_tenant_onboarding(body: TenantOnboardingRequest, db: Session = Depends(get_db)) -> OnboardingResponse:
    tenant = create_tenant(db, body, settings.collector_intervals_minutes)
    db.flush()
    db.commit()
    db.refresh(tenant)
    return OnboardingResponse(tenant=_tenant_to_response(tenant), consent_url=build_onboarding_response(tenant))


@app.get("/api/v1/onboarding/callback", response_model=TenantResponse)
def onboarding_callback(
    tenant: str,
    state: str,
    admin_consent: str = Query(default=""),
    db: Session = Depends(get_db),
) -> TenantResponse:
    if admin_consent.lower() not in {"true", "yes", "1"}:
        raise HTTPException(status_code=400, detail="Admin consent was not granted")
    record = complete_admin_consent(db, state, tenant)
    db.flush()
    db.commit()
    db.refresh(record)
    return _tenant_to_response(record)


@app.get("/api/v1/tenants", response_model=list[TenantResponse])
def list_tenants(db: Session = Depends(get_db)) -> list[TenantResponse]:
    return [_tenant_to_response(item) for item in db.execute(select(Tenant).order_by(Tenant.created_at.desc())).scalars()]


@app.post("/api/v1/tenants/{tenant_id}/credentials", response_model=TenantResponse)
def store_tenant_credentials(
    tenant_id: str,
    body: TenantCredentialRequest,
    db: Session = Depends(get_db),
) -> TenantResponse:
    tenant = db.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    upsert_tenant_credential(db, tenant_id, body)
    db.flush()
    db.commit()
    db.refresh(tenant)
    return _tenant_to_response(tenant)


@app.post("/api/v1/tenants/{tenant_id}/runs", response_model=IngestionRunResponse)
def create_run(tenant_id: str, body: RunEnqueueRequest, db: Session = Depends(get_db)) -> IngestionRunResponse:
    tenant = db.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    collector = registry.get(body.source)
    if collector is None:
        raise HTTPException(status_code=400, detail="Unknown collector source")
    run = enqueue_run(
        db,
        tenant_id=tenant_id,
        source=body.source,
        collector=collector.__class__.__name__,
        scope_json={"subscription_ids": body.subscription_ids},
    )
    db.flush()
    db.commit()
    db.refresh(run)
    return IngestionRunResponse.model_validate(run, from_attributes=True)


@app.get("/api/v1/ingestion-runs", response_model=list[IngestionRunResponse])
def list_runs(
    tenant_id: str | None = None,
    source: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[IngestionRunResponse]:
    query = select(IngestionRun).order_by(IngestionRun.scheduled_at.desc()).limit(limit)
    if tenant_id:
        query = query.where(IngestionRun.tenant_id == tenant_id)
    if source:
        query = query.where(IngestionRun.source == source)
    return [IngestionRunResponse.model_validate(item, from_attributes=True) for item in db.execute(query).scalars()]


@app.get("/api/v1/collector-status", response_model=list[CollectorStatusResponse])
def collector_status(db: Session = Depends(get_db)) -> list[CollectorStatusResponse]:
    rows = db.execute(select(CollectorSchedule)).scalars().all()
    results: list[CollectorStatusResponse] = []
    now = datetime.now(timezone.utc)
    for schedule in rows:
        latest_run = db.execute(
            select(IngestionRun)
            .where(IngestionRun.tenant_id == schedule.tenant_id, IngestionRun.source == schedule.source)
            .order_by(IngestionRun.scheduled_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        pending_runs = db.scalar(
            select(func.count()).select_from(IngestionRun).where(
                IngestionRun.tenant_id == schedule.tenant_id,
                IngestionRun.source == schedule.source,
                IngestionRun.status == "pending",
            )
        ) or 0
        lag_seconds = None
        if latest_run and latest_run.finished_at:
            lag_seconds = int((now - latest_run.finished_at).total_seconds())
        results.append(
            CollectorStatusResponse(
                tenant_id=schedule.tenant_id,
                source=schedule.source,
                enabled=schedule.enabled,
                interval_minutes=schedule.interval_minutes,
                last_run_status=latest_run.status if latest_run else None,
                last_finished_at=latest_run.finished_at if latest_run else None,
                lag_seconds=lag_seconds,
                pending_runs=int(pending_runs),
            )
        )
    return results


@app.get("/api/v1/resources/current", response_model=list[ResourceRowResponse])
def list_resources(
    tenant_id: str | None = None,
    resource_type: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[ResourceRowResponse]:
    query = select(ResourceCurrent).order_by(ResourceCurrent.last_seen_at.desc()).limit(limit)
    if tenant_id:
        query = query.where(ResourceCurrent.tenant_id == tenant_id)
    if resource_type:
        query = query.where(ResourceCurrent.resource_type == resource_type)
    return [ResourceRowResponse.model_validate(item, from_attributes=True) for item in db.execute(query).scalars()]


@app.get("/api/v1/activity-events", response_model=list[ActivityEventResponse])
def list_activity_events(
    tenant_id: str | None = None,
    subscription_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[ActivityEventResponse]:
    query = select(ActivityEvent).order_by(ActivityEvent.event_timestamp.desc()).limit(limit)
    if tenant_id:
        query = query.where(ActivityEvent.tenant_id == tenant_id)
    if subscription_id:
        query = query.where(ActivityEvent.subscription_id == subscription_id)
    return [ActivityEventResponse.model_validate(item, from_attributes=True) for item in db.execute(query).scalars()]


@app.get("/api/v1/raw-payloads", response_model=list[RawPayloadResponse])
def list_raw_payloads(
    tenant_id: str | None = None,
    source: str | None = None,
    run_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[RawPayloadResponse]:
    query = select(RawPayload).order_by(RawPayload.received_at.desc()).limit(limit)
    if tenant_id:
        query = query.where(RawPayload.tenant_id == tenant_id)
    if source:
        query = query.where(RawPayload.source == source)
    if run_id:
        query = query.where(RawPayload.run_id == run_id)
    return [RawPayloadResponse.model_validate(item, from_attributes=True) for item in db.execute(query).scalars()]
