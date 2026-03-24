from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import CollectorSchedule, IngestionCheckpoint, IngestionRun, Tenant


def enqueue_run(
    db: Session,
    *,
    tenant_id: str,
    source: str,
    collector: str,
    scope_json: dict[str, Any] | None = None,
) -> IngestionRun:
    run = IngestionRun(
        tenant_id=tenant_id,
        source=source,
        collector=collector,
        status="pending",
        scheduled_at=datetime.now(timezone.utc),
        scope_json=scope_json or {},
        stats_json={},
        worker_id="",
        error_text="",
    )
    db.add(run)
    return run


def due_schedules(db: Session) -> list[tuple[Tenant, CollectorSchedule]]:
    now = datetime.now(timezone.utc)
    rows = (
        db.query(Tenant, CollectorSchedule)
        .join(CollectorSchedule, CollectorSchedule.tenant_id == Tenant.id)
        .filter(Tenant.status == "active", CollectorSchedule.enabled.is_(True))
        .all()
    )
    due: list[tuple[Tenant, CollectorSchedule]] = []
    for tenant, schedule in rows:
        pending_or_running = db.scalar(
            select(func.count())
            .select_from(IngestionRun)
            .where(
                IngestionRun.tenant_id == tenant.id,
                IngestionRun.source == schedule.source,
                IngestionRun.status.in_(["pending", "running"]),
            )
        )
        if pending_or_running:
            continue
        if schedule.last_enqueued_at is None or schedule.last_enqueued_at <= now - timedelta(minutes=schedule.interval_minutes):
            due.append((tenant, schedule))
    return due


def claim_next_run(db: Session, *, worker_id: str) -> IngestionRun | None:
    runs = (
        db.query(IngestionRun)
        .filter(IngestionRun.status == "pending")
        .order_by(IngestionRun.scheduled_at.asc())
        .all()
    )
    for run in runs:
        running_for_source = db.scalar(
            select(func.count())
            .select_from(IngestionRun)
            .where(IngestionRun.source == run.source, IngestionRun.status == "running")
        )
        limit = int(settings.source_concurrency_limits.get(run.source, 1) or 1)
        if running_for_source >= limit:
            continue
        run.status = "running"
        run.worker_id = worker_id
        run.attempt_count += 1
        run.started_at = datetime.now(timezone.utc)
        return run
    return None


def load_checkpoints(db: Session, tenant_id: str, source: str) -> dict[str, IngestionCheckpoint]:
    rows = db.execute(
        select(IngestionCheckpoint).where(
            IngestionCheckpoint.tenant_id == tenant_id,
            IngestionCheckpoint.source == source,
        )
    ).scalars()
    return {row.scope_key: row for row in rows}


def save_checkpoints(db: Session, tenant_id: str, items: list[tuple[str, str, str, dict[str, Any]]]) -> None:
    for source, scope_key, watermark, state in items:
        checkpoint = db.execute(
            select(IngestionCheckpoint).where(
                IngestionCheckpoint.tenant_id == tenant_id,
                IngestionCheckpoint.source == source,
                IngestionCheckpoint.scope_key == scope_key,
            )
        ).scalar_one_or_none()
        if checkpoint is None:
            checkpoint = IngestionCheckpoint(
                tenant_id=tenant_id,
                source=source,
                scope_key=scope_key,
                cursor="",
                watermark=watermark,
                state_json=state,
            )
            db.add(checkpoint)
        else:
            checkpoint.watermark = watermark
            checkpoint.state_json = state


def finish_run(db: Session, run: IngestionRun, *, status: str, stats_json: dict[str, Any] | None = None, error_text: str = "") -> None:
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.stats_json = stats_json or {}
    run.error_text = error_text
