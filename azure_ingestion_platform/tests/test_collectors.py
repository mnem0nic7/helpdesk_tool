from __future__ import annotations

import importlib
from datetime import datetime, timezone


class FakeResourceGraphClient:
    def __init__(self, payloads):
        self.payloads = payloads

    def list_subscriptions(self):
        return [
            {
                "subscriptionId": "sub-001",
                "displayName": "Prod",
                "state": "Enabled",
                "authorizationSource": "RoleBased",
            }
        ]

    def iter_resource_graph_pages(self, subscriptions, query):
        return iter(self.payloads)

    def payload_hash(self, payload):
        return f"hash:{len(str(payload))}"


class FakeActivityLogClient:
    def __init__(self, payloads):
        self.payloads = payloads

    def iter_activity_log_pages(self, subscription_id, start, end):
        return iter(self.payloads)

    def payload_hash(self, payload):
        return f"hash:{len(str(payload))}"


def test_resource_graph_collector_upserts_and_soft_deletes(platform_env):
    db = importlib.import_module("azure_ingestion_platform.db")
    models = importlib.import_module("azure_ingestion_platform.models")
    base = importlib.import_module("azure_ingestion_platform.collectors.base")
    module = importlib.import_module("azure_ingestion_platform.collectors.resource_graph")
    db.Base.metadata.create_all(db.engine)

    with db.session_scope() as session:
        tenant = models.Tenant(
            tenant_external_id="tenant-a",
            slug="tenant-a",
            display_name="Tenant A",
            status="active",
            consent_state="state-a",
            metadata_json={},
        )
        run = models.IngestionRun(tenant_id=tenant.id, source="resource_graph", collector="ResourceGraphCollector", scope_json={}, stats_json={}, worker_id="", error_text="")
        session.add(tenant)
        session.flush()
        run.tenant_id = tenant.id
        session.add(run)
        session.flush()

        collector = module.ResourceGraphCollector()
        context = base.CollectorContext(
            db=session,
            tenant=tenant,
            run=run,
            client=FakeResourceGraphClient(
                [
                    {
                        "data": [
                            {
                                "id": "/subscriptions/sub-001/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
                                "subscriptionId": "sub-001",
                                "name": "vm-1",
                                "type": "Microsoft.Compute/virtualMachines",
                                "resourceGroup": "rg",
                                "location": "eastus",
                                "kind": "",
                                "tags": {"team": "Platform"},
                                "identity": {},
                                "managedBy": "",
                                "sku": {},
                                "properties": {"powerState": "running"},
                            }
                        ]
                    }
                ]
            ),
            checkpoint_map={},
            now=datetime.now(timezone.utc),
        )
        result = collector.collect(context)
        assert result.stats["created"] == 1

    with db.session_scope() as session:
        tenant = session.query(models.Tenant).filter_by(slug="tenant-a").one()
        run = models.IngestionRun(tenant_id=tenant.id, source="resource_graph", collector="ResourceGraphCollector", scope_json={}, stats_json={}, worker_id="", error_text="")
        session.add(run)
        session.flush()
        collector = module.ResourceGraphCollector()
        context = base.CollectorContext(
            db=session,
            tenant=tenant,
            run=run,
            client=FakeResourceGraphClient([{"data": []}]),
            checkpoint_map={},
            now=datetime.now(timezone.utc),
        )
        result = collector.collect(context)
        assert result.stats["deleted"] == 1
        current = session.query(models.ResourceCurrent).one()
        assert current.is_deleted is True


def test_activity_log_collector_persists_events_and_checkpoints(platform_env):
    db = importlib.import_module("azure_ingestion_platform.db")
    models = importlib.import_module("azure_ingestion_platform.models")
    base = importlib.import_module("azure_ingestion_platform.collectors.base")
    module = importlib.import_module("azure_ingestion_platform.collectors.activity_log")
    db.Base.metadata.create_all(db.engine)

    with db.session_scope() as session:
        tenant = models.Tenant(
            tenant_external_id="tenant-b",
            slug="tenant-b",
            display_name="Tenant B",
            status="active",
            consent_state="state-b",
            metadata_json={},
        )
        session.add(tenant)
        session.flush()
        session.add(
            models.Subscription(
                tenant_id=tenant.id,
                subscription_id="sub-002",
                display_name="Prod",
                state="Enabled",
                authorization_source="RoleBased",
            )
        )
        run = models.IngestionRun(tenant_id=tenant.id, source="activity_log", collector="ActivityLogCollector", scope_json={}, stats_json={}, worker_id="", error_text="")
        session.add(run)
        session.flush()
        collector = module.ActivityLogCollector()
        context = base.CollectorContext(
            db=session,
            tenant=tenant,
            run=run,
            client=FakeActivityLogClient(
                [
                    {
                        "value": [
                            {
                                "eventDataId": "evt-1",
                                "eventTimestamp": "2026-03-23T00:00:00Z",
                                "category": {"value": "Administrative"},
                                "operationName": {"value": "Microsoft.Compute/virtualMachines/write"},
                                "status": {"value": "Succeeded"},
                                "caller": "admin@contoso.com",
                                "correlationId": "corr-1",
                                "level": "Informational",
                            }
                        ]
                    }
                ]
            ),
            checkpoint_map={},
            now=datetime.now(timezone.utc),
        )
        result = collector.collect(context)
        assert result.stats["inserted_events"] == 1

        checkpoints = {item[1]: item for item in result.checkpoints}
        assert "subscription:sub-002" in checkpoints
