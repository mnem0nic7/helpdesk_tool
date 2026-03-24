"""initial multi-tenant azure ingestion schema"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260323_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_external_id", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("consent_state", sa.String(length=128), nullable=False),
        sa.Column("onboarded_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_external_id"),
        sa.UniqueConstraint("slug"),
        sa.UniqueConstraint("consent_state"),
    )
    op.create_index("ix_tenants_status", "tenants", ["status"])

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("collector", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=120), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("stats_json", sa.JSON(), nullable=False),
        sa.Column("error_text", sa.Text(), nullable=False),
    )
    op.create_index("ix_ingestion_runs_tenant", "ingestion_runs", ["tenant_id"])
    op.create_index("ix_ingestion_runs_source", "ingestion_runs", ["source"])
    op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])
    op.create_index("ix_ingestion_runs_scheduled", "ingestion_runs", ["scheduled_at"])

    op.create_table(
        "raw_payloads",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("ingestion_runs.id")),
        sa.Column("subscription_id", sa.String(length=128), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("request_url", sa.Text(), nullable=False),
        sa.Column("continuation_token", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=128), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_raw_payloads_tenant", "raw_payloads", ["tenant_id"])
    op.create_index("ix_raw_payloads_source", "raw_payloads", ["source"])
    op.create_index("ix_raw_payloads_subscription", "raw_payloads", ["subscription_id"])
    op.create_index("ix_raw_payloads_hash", "raw_payloads", ["payload_hash"])
    op.create_index("ix_raw_payloads_received", "raw_payloads", ["received_at"])

    op.create_table(
        "tenant_credentials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credential_type", sa.String(length=40), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("secret_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "credential_type", name="uq_tenant_credentials_type"),
    )
    op.create_index("ix_tenant_credentials_tenant", "tenant_credentials", ["tenant_id"])
    op.create_index("ix_tenant_credentials_type", "tenant_credentials", ["credential_type"])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=80), nullable=False),
        sa.Column("authorization_source", sa.String(length=80), nullable=False),
        sa.Column("raw_payload_id", sa.String(length=36), sa.ForeignKey("raw_payloads.id")),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "subscription_id", name="uq_tenant_subscription"),
    )
    op.create_index("ix_subscriptions_tenant", "subscriptions", ["tenant_id"])
    op.create_index("ix_subscriptions_subscription", "subscriptions", ["subscription_id"])

    op.create_table(
        "ingestion_checkpoints",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("scope_key", sa.String(length=255), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=False),
        sa.Column("watermark", sa.String(length=80), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "source", "scope_key", name="uq_ingestion_checkpoint_scope"),
    )
    op.create_index("ix_ingestion_checkpoints_tenant", "ingestion_checkpoints", ["tenant_id"])
    op.create_index("ix_ingestion_checkpoints_source", "ingestion_checkpoints", ["source"])
    op.create_index("ix_ingestion_checkpoints_scope", "ingestion_checkpoints", ["scope_key"])

    op.create_table(
        "collector_schedules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "source", name="uq_collector_schedule"),
    )
    op.create_index("ix_collector_schedules_tenant", "collector_schedules", ["tenant_id"])
    op.create_index("ix_collector_schedules_source", "collector_schedules", ["source"])

    op.create_table(
        "resources_current",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("resource_type", sa.String(length=255), nullable=False),
        sa.Column("resource_group", sa.String(length=255), nullable=False),
        sa.Column("location", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=120), nullable=False),
        sa.Column("sku", sa.JSON(), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("identity_json", sa.JSON(), nullable=False),
        sa.Column("managed_by", sa.Text(), nullable=False),
        sa.Column("properties_json", sa.JSON(), nullable=False),
        sa.Column("source_hash", sa.String(length=128), nullable=False),
        sa.Column("last_seen_run_id", sa.String(length=36), sa.ForeignKey("ingestion_runs.id")),
        sa.Column("raw_payload_id", sa.String(length=36), sa.ForeignKey("raw_payloads.id")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "subscription_id", "resource_id", name="uq_current_resource"),
    )
    for name, cols in {
        "ix_resources_current_tenant": ["tenant_id"],
        "ix_resources_current_subscription": ["subscription_id"],
        "ix_resources_current_type": ["resource_type"],
        "ix_resources_current_group": ["resource_group"],
        "ix_resources_current_hash": ["source_hash"],
        "ix_resources_current_deleted": ["is_deleted"],
    }.items():
        op.create_index(name, "resources_current", cols)

    op.create_table(
        "resources_history",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("change_kind", sa.String(length=40), nullable=False),
        sa.Column("source_hash", sa.String(length=128), nullable=False),
        sa.Column("properties_json", sa.JSON(), nullable=False),
        sa.Column("raw_payload_id", sa.String(length=36), sa.ForeignKey("raw_payloads.id")),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("ingestion_runs.id")),
    )
    op.create_index("ix_resources_history_tenant", "resources_history", ["tenant_id"])
    op.create_index("ix_resources_history_subscription", "resources_history", ["subscription_id"])
    op.create_index("ix_resources_history_resource", "resources_history", ["resource_id"])
    op.create_index("ix_resources_history_observed", "resources_history", ["observed_at"])
    op.create_index("ix_resources_history_hash", "resources_history", ["source_hash"])

    op.create_table(
        "activity_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(length=128), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True)),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("operation_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=120), nullable=False),
        sa.Column("caller", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("level", sa.String(length=80), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("raw_payload_id", sa.String(length=36), sa.ForeignKey("raw_payloads.id")),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("ingestion_runs.id")),
        sa.UniqueConstraint("tenant_id", "subscription_id", "event_id", name="uq_activity_event"),
    )
    for name, cols in {
        "ix_activity_events_tenant": ["tenant_id"],
        "ix_activity_events_subscription": ["subscription_id"],
        "ix_activity_events_event_id": ["event_id"],
        "ix_activity_events_timestamp": ["event_timestamp"],
        "ix_activity_events_operation": ["operation_name"],
    }.items():
        op.create_index(name, "activity_events", cols)

    op.create_table(
        "resource_changes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("change_timestamp", sa.DateTime(timezone=True)),
        sa.Column("change_type", sa.String(length=120), nullable=False),
        sa.Column("changed_properties_json", sa.JSON(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("raw_payload_id", sa.String(length=36), sa.ForeignKey("raw_payloads.id")),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("ingestion_runs.id")),
    )
    op.create_index("ix_resource_changes_tenant", "resource_changes", ["tenant_id"])
    op.create_index("ix_resource_changes_subscription", "resource_changes", ["subscription_id"])
    op.create_index("ix_resource_changes_resource", "resource_changes", ["resource_id"])
    op.create_index("ix_resource_changes_timestamp", "resource_changes", ["change_timestamp"])

    op.create_table(
        "metric_points",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("metric_namespace", sa.String(length=255), nullable=False),
        sa.Column("metric_name", sa.String(length=255), nullable=False),
        sa.Column("aggregation", sa.String(length=80), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True)),
        sa.Column("average", sa.Float()),
        sa.Column("minimum", sa.Float()),
        sa.Column("maximum", sa.Float()),
        sa.Column("total", sa.Float()),
        sa.Column("count", sa.Float()),
        sa.Column("dimensions_json", sa.JSON(), nullable=False),
        sa.Column("raw_payload_id", sa.String(length=36), sa.ForeignKey("raw_payloads.id")),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("ingestion_runs.id")),
    )
    for name, cols in {
        "ix_metric_points_tenant": ["tenant_id"],
        "ix_metric_points_subscription": ["subscription_id"],
        "ix_metric_points_resource": ["resource_id"],
        "ix_metric_points_metric": ["metric_name"],
        "ix_metric_points_timestamp": ["timestamp"],
    }.items():
        op.create_index(name, "metric_points", cols)

    op.create_table(
        "cost_usage",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(length=128), nullable=False),
        sa.Column("usage_date", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("resource_group", sa.String(length=255), nullable=False),
        sa.Column("service_name", sa.String(length=255), nullable=False),
        sa.Column("meter_category", sa.String(length=255), nullable=False),
        sa.Column("currency", sa.String(length=32), nullable=False),
        sa.Column("cost_actual", sa.Float(), nullable=False),
        sa.Column("cost_amortized", sa.Float(), nullable=False),
        sa.Column("usage_quantity", sa.Float(), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("pricing_model", sa.String(length=120), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("raw_payload_id", sa.String(length=36), sa.ForeignKey("raw_payloads.id")),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("ingestion_runs.id")),
    )
    for name, cols in {
        "ix_cost_usage_tenant": ["tenant_id"],
        "ix_cost_usage_subscription": ["subscription_id"],
        "ix_cost_usage_date": ["usage_date"],
        "ix_cost_usage_resource": ["resource_id"],
    }.items():
        op.create_index(name, "cost_usage", cols)

    op.create_table(
        "advisor_recommendations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(length=128), nullable=False),
        sa.Column("recommendation_id", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("impact", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("potential_savings", sa.Float()),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("raw_payload_id", sa.String(length=36), sa.ForeignKey("raw_payloads.id")),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("ingestion_runs.id")),
        sa.UniqueConstraint("tenant_id", "subscription_id", "recommendation_id", name="uq_advisor_recommendation"),
    )
    op.create_index("ix_advisor_recommendations_tenant", "advisor_recommendations", ["tenant_id"])
    op.create_index("ix_advisor_recommendations_subscription", "advisor_recommendations", ["subscription_id"])
    op.create_index("ix_advisor_recommendations_recommendation", "advisor_recommendations", ["recommendation_id"])

    op.create_table(
        "entra_directory_audits",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audit_id", sa.String(length=255), nullable=False),
        sa.Column("activity_datetime", sa.DateTime(timezone=True)),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("activity_display_name", sa.String(length=255), nullable=False),
        sa.Column("initiated_by", sa.String(length=255), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("raw_payload_id", sa.String(length=36), sa.ForeignKey("raw_payloads.id")),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("ingestion_runs.id")),
        sa.UniqueConstraint("tenant_id", "audit_id", name="uq_entra_directory_audit"),
    )
    op.create_index("ix_entra_directory_audits_tenant", "entra_directory_audits", ["tenant_id"])
    op.create_index("ix_entra_directory_audits_audit_id", "entra_directory_audits", ["audit_id"])
    op.create_index("ix_entra_directory_audits_datetime", "entra_directory_audits", ["activity_datetime"])

    op.create_table(
        "entra_signins",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signin_id", sa.String(length=255), nullable=False),
        sa.Column("created_datetime", sa.DateTime(timezone=True)),
        sa.Column("user_principal_name", sa.String(length=255), nullable=False),
        sa.Column("app_display_name", sa.String(length=255), nullable=False),
        sa.Column("status_json", sa.JSON(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("raw_payload_id", sa.String(length=36), sa.ForeignKey("raw_payloads.id")),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("ingestion_runs.id")),
        sa.UniqueConstraint("tenant_id", "signin_id", name="uq_entra_signin"),
    )
    op.create_index("ix_entra_signins_tenant", "entra_signins", ["tenant_id"])
    op.create_index("ix_entra_signins_signin_id", "entra_signins", ["signin_id"])
    op.create_index("ix_entra_signins_created", "entra_signins", ["created_datetime"])


def downgrade() -> None:
    for table in [
        "entra_signins",
        "entra_directory_audits",
        "advisor_recommendations",
        "cost_usage",
        "metric_points",
        "resource_changes",
        "activity_events",
        "resources_history",
        "resources_current",
        "collector_schedules",
        "ingestion_checkpoints",
        "subscriptions",
        "tenant_credentials",
        "raw_payloads",
        "ingestion_runs",
        "tenants",
    ]:
        op.drop_table(table)
