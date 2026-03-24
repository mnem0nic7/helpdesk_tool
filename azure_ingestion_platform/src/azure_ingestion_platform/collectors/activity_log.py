from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..models import ActivityEvent, IngestionCheckpoint, RawPayload, Subscription
from .base import CollectorContext, CollectorPlugin, CollectorResult


class ActivityLogCollector(CollectorPlugin):
    source = "activity_log"
    kind = "incremental"
    description = "Incremental Azure Activity Log ingestion for control-plane events."
    implemented = True

    def default_interval_minutes(self) -> int:
        return 5

    def collect(self, context: CollectorContext) -> CollectorResult:
        subscriptions = context.db.execute(
            select(Subscription).where(Subscription.tenant_id == context.tenant.id)
        ).scalars().all()
        processed = 0
        inserted = 0
        payload_pages = 0
        checkpoints: list[tuple[str, str, str, dict[str, str]]] = []

        for subscription in subscriptions:
            scope_key = f"subscription:{subscription.subscription_id}"
            checkpoint = context.checkpoint_map.get(scope_key)
            start = context.now - timedelta(hours=1)
            if checkpoint and checkpoint.watermark:
                try:
                    start = datetime.fromisoformat(checkpoint.watermark.replace("Z", "+00:00")).astimezone(timezone.utc)
                except ValueError:
                    start = context.now - timedelta(hours=1)
            end = context.now

            for payload in context.client.iter_activity_log_pages(subscription.subscription_id, start, end):
                payload_pages += 1
                raw_payload = RawPayload(
                    tenant_id=context.tenant.id,
                    source=self.source,
                    run_id=context.run.id,
                    subscription_id=subscription.subscription_id,
                    endpoint="activity_log",
                    request_url=(
                        f"https://management.azure.com/subscriptions/{subscription.subscription_id}/providers/"
                        "microsoft.insights/eventtypes/management/values"
                    ),
                    continuation_token=str(payload.get("nextLink") or ""),
                    payload_json=payload,
                    payload_hash=context.client.payload_hash(payload),
                )
                context.db.add(raw_payload)
                context.db.flush()

                for event in payload.get("value") or []:
                    if not isinstance(event, dict):
                        continue
                    event_id = str(event.get("eventDataId") or event.get("id") or "")
                    if not event_id:
                        continue
                    processed += 1
                    existing = context.db.execute(
                        select(ActivityEvent).where(
                            ActivityEvent.tenant_id == context.tenant.id,
                            ActivityEvent.subscription_id == subscription.subscription_id,
                            ActivityEvent.event_id == event_id,
                        )
                    ).scalar_one_or_none()
                    if existing is None:
                        existing = ActivityEvent(
                            tenant_id=context.tenant.id,
                            subscription_id=subscription.subscription_id,
                            event_id=event_id,
                        )
                        context.db.add(existing)
                        inserted += 1
                    existing.event_timestamp = _parse_event_datetime(event.get("eventTimestamp"))
                    existing.category = str((event.get("category") or {}).get("value") or event.get("category") or "")
                    existing.operation_name = str((event.get("operationName") or {}).get("value") or "")
                    existing.status = str((event.get("status") or {}).get("value") or "")
                    existing.caller = str(event.get("caller") or "")
                    existing.correlation_id = str(event.get("correlationId") or "")
                    existing.level = str(event.get("level") or "")
                    existing.payload_json = event
                    existing.raw_payload_id = raw_payload.id
                    existing.run_id = context.run.id

            checkpoints.append((self.source, scope_key, end.isoformat(), {"subscription_id": subscription.subscription_id}))

        return CollectorResult(
            source=self.source,
            status="succeeded",
            stats={
                "subscriptions": len(subscriptions),
                "payload_pages": payload_pages,
                "processed_events": processed,
                "inserted_events": inserted,
            },
            checkpoints=checkpoints,
        )


def _parse_event_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
