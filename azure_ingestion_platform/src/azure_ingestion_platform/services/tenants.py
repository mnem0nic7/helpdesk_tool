from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..azure import build_admin_consent_url
from ..models import CollectorSchedule, Tenant, TenantCredential
from ..schemas import TenantCredentialRequest, TenantOnboardingRequest
from ..security import cipher


def create_tenant(db: Session, body: TenantOnboardingRequest, collector_intervals: dict[str, int]) -> Tenant:
    tenant = Tenant(
        tenant_external_id=body.tenant_external_id,
        slug=body.slug,
        display_name=body.display_name,
        status="pending_consent",
        consent_state=_tenant_state(body.tenant_external_id, body.slug),
        metadata_json={},
    )
    db.add(tenant)
    db.flush()
    for source, interval in collector_intervals.items():
        db.add(
            CollectorSchedule(
                tenant_id=tenant.id,
                source=source,
                interval_minutes=int(interval),
                enabled=source in {"resource_graph", "activity_log"},
                scope_json={},
            )
        )
    return tenant


def complete_admin_consent(db: Session, state: str, tenant_external_id: str) -> Tenant:
    tenant = db.execute(select(Tenant).where(Tenant.consent_state == state)).scalar_one()
    tenant.tenant_external_id = tenant_external_id
    tenant.status = "active"
    tenant.onboarded_at = datetime.now(timezone.utc)
    tenant.last_seen_at = tenant.onboarded_at
    return tenant


def upsert_tenant_credential(db: Session, tenant_id: str, body: TenantCredentialRequest) -> TenantCredential:
    credential = db.execute(
        select(TenantCredential).where(
            TenantCredential.tenant_id == tenant_id,
            TenantCredential.credential_type == body.credential_type,
        )
    ).scalar_one_or_none()
    if credential is None:
        credential = TenantCredential(tenant_id=tenant_id, credential_type=body.credential_type)
        db.add(credential)
    credential.client_id = body.client_id
    credential.secret_encrypted = cipher.encrypt(body.client_secret)
    credential.secret_fingerprint = cipher.fingerprint(body.client_secret)
    credential.metadata_json = body.metadata
    return credential


def build_onboarding_response(tenant: Tenant) -> str:
    return build_admin_consent_url(tenant.consent_state)


def _tenant_state(tenant_external_id: str, slug: str) -> str:
    return f"{tenant_external_id}:{slug}:{int(datetime.now(timezone.utc).timestamp())}"
