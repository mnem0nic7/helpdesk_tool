from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..models import RawPayload, ResourceCurrent, ResourceHistory, Subscription
from .base import CollectorContext, CollectorPlugin, CollectorResult


RESOURCE_GRAPH_QUERY = """
Resources
| project id, name, type, resourceGroup, subscriptionId, location, kind, tags, identity, managedBy, sku, properties
"""


def _resource_hash(row: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class ResourceGraphCollector(CollectorPlugin):
    source = "resource_graph"
    kind = "snapshot"
    description = "Azure Resource Graph inventory snapshot with soft-delete handling."
    implemented = True

    def default_interval_minutes(self) -> int:
        return 360

    def collect(self, context: CollectorContext) -> CollectorResult:
        subscriptions = context.client.list_subscriptions()
        subscription_ids = [str(item.get("subscriptionId") or "") for item in subscriptions if item.get("subscriptionId")]
        seen: set[tuple[str, str]] = set()
        payload_count = 0
        resource_count = 0
        created = 0
        updated = 0
        deleted = 0

        for raw_subscription in subscriptions:
            subscription_id = str(raw_subscription.get("subscriptionId") or "")
            if not subscription_id:
                continue
            existing = context.db.execute(
                select(Subscription).where(
                    Subscription.tenant_id == context.tenant.id,
                    Subscription.subscription_id == subscription_id,
                )
            ).scalar_one_or_none()
            if existing is None:
                existing = Subscription(
                    tenant_id=context.tenant.id,
                    subscription_id=subscription_id,
                    display_name=str(raw_subscription.get("displayName") or ""),
                    state=str(raw_subscription.get("state") or ""),
                    authorization_source=str(raw_subscription.get("authorizationSource") or ""),
                )
                context.db.add(existing)
            else:
                existing.display_name = str(raw_subscription.get("displayName") or "")
                existing.state = str(raw_subscription.get("state") or "")
                existing.authorization_source = str(raw_subscription.get("authorizationSource") or "")

        if not subscription_ids:
            return CollectorResult(
                source=self.source,
                status="succeeded",
                stats={"subscriptions": 0, "payload_pages": 0, "resource_rows": 0, "created": 0, "updated": 0, "deleted": 0},
                checkpoints=[("resource_graph", "tenant_snapshot", context.now.isoformat(), {"subscription_count": 0})],
            )

        for payload in context.client.iter_resource_graph_pages(subscription_ids, RESOURCE_GRAPH_QUERY):
            payload_count += 1
            raw_payload = RawPayload(
                tenant_id=context.tenant.id,
                source=self.source,
                run_id=context.run.id,
                subscription_id=",".join(subscription_ids),
                endpoint="resource_graph",
                request_url="https://management.azure.com/providers/Microsoft.ResourceGraph/resources",
                continuation_token=str(payload.get("skipToken") or ""),
                payload_json=payload,
                payload_hash=context.client.payload_hash(payload),
            )
            context.db.add(raw_payload)
            context.db.flush()

            for row in payload.get("data") or []:
                if not isinstance(row, dict):
                    continue
                resource_id = str(row.get("id") or "")
                subscription_id = str(row.get("subscriptionId") or "")
                if not resource_id or not subscription_id:
                    continue
                seen.add((subscription_id, resource_id))
                resource_count += 1
                normalized_hash = _resource_hash(row)
                current = context.db.execute(
                    select(ResourceCurrent).where(
                        ResourceCurrent.tenant_id == context.tenant.id,
                        ResourceCurrent.subscription_id == subscription_id,
                        ResourceCurrent.resource_id == resource_id,
                    )
                ).scalar_one_or_none()
                change_kind = "unchanged"
                if current is None:
                    current = ResourceCurrent(
                        tenant_id=context.tenant.id,
                        subscription_id=subscription_id,
                        resource_id=resource_id,
                        first_seen_at=context.now,
                    )
                    context.db.add(current)
                    created += 1
                    change_kind = "created"
                elif current.source_hash != normalized_hash or current.is_deleted:
                    updated += 1
                    change_kind = "updated"

                current.name = str(row.get("name") or "")
                current.resource_type = str(row.get("type") or "")
                current.resource_group = str(row.get("resourceGroup") or "")
                current.location = str(row.get("location") or "")
                current.kind = str(row.get("kind") or "")
                current.sku = row.get("sku") or {}
                current.tags_json = row.get("tags") or {}
                current.identity_json = row.get("identity") or {}
                current.managed_by = str(row.get("managedBy") or "")
                current.properties_json = row.get("properties") or {}
                current.source_hash = normalized_hash
                current.last_seen_run_id = context.run.id
                current.raw_payload_id = raw_payload.id
                current.last_seen_at = context.now
                current.is_deleted = False
                current.deleted_at = None

                if change_kind != "unchanged":
                    context.db.add(
                        ResourceHistory(
                            tenant_id=context.tenant.id,
                            subscription_id=subscription_id,
                            resource_id=resource_id,
                            observed_at=context.now,
                            change_kind=change_kind,
                            source_hash=normalized_hash,
                            properties_json=row,
                            raw_payload_id=raw_payload.id,
                            run_id=context.run.id,
                        )
                    )

        existing_resources = context.db.execute(
            select(ResourceCurrent).where(
                ResourceCurrent.tenant_id == context.tenant.id,
                ResourceCurrent.subscription_id.in_(subscription_ids) if subscription_ids else False,
                ResourceCurrent.is_deleted.is_(False),
            )
        ).scalars()
        for current in existing_resources:
            key = (current.subscription_id, current.resource_id)
            if key in seen:
                continue
            current.is_deleted = True
            current.deleted_at = context.now
            current.last_seen_at = context.now
            deleted += 1
            context.db.add(
                ResourceHistory(
                    tenant_id=current.tenant_id,
                    subscription_id=current.subscription_id,
                    resource_id=current.resource_id,
                    observed_at=context.now,
                    change_kind="deleted",
                    source_hash=current.source_hash,
                    properties_json=current.properties_json,
                    raw_payload_id=current.raw_payload_id,
                    run_id=context.run.id,
                )
            )

        return CollectorResult(
            source=self.source,
            status="succeeded",
            stats={
                "subscriptions": len(subscription_ids),
                "payload_pages": payload_count,
                "resource_rows": resource_count,
                "created": created,
                "updated": updated,
                "deleted": deleted,
            },
            checkpoints=[
                ("resource_graph", "tenant_snapshot", context.now.isoformat(), {"subscription_count": len(subscription_ids)})
            ],
        )
