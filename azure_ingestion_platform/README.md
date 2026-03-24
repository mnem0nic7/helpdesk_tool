# Azure Ingestion Platform

Production-oriented starter platform for multi-tenant Azure data ingestion with:

- FastAPI web service
- scheduler service
- worker service
- PostgreSQL backend
- raw payload retention plus normalized SQL tables
- plugin-style collector framework
- starter collectors for Azure Resource Graph and Azure Activity Log

## Repository Structure

```text
azure_ingestion_platform/
  Dockerfile
  docker-compose.yml
  requirements.txt
  alembic.ini
  migrations/
    env.py
    versions/
      20260323_0001_initial.py
  src/azure_ingestion_platform/
    config.py
    db.py
    models.py
    security.py
    azure.py
    main.py
    cli_scheduler.py
    cli_worker.py
    collectors/
      base.py
      registry.py
      resource_graph.py
      activity_log.py
      placeholders.py
    services/
      tenants.py
      jobs.py
      scheduler.py
      worker.py
  tests/
```

## What Is Implemented

### Platform capabilities

- Multi-tenant tenant registry with per-tenant onboarding state
- Admin-consent onboarding flow for Microsoft Entra multi-tenant apps
- Secure storage for optional per-tenant client secret overrides
- SQL schema for:
  - `tenants`
  - `tenant_credentials`
  - `subscriptions`
  - `resources_current`
  - `resources_history`
  - `activity_events`
  - `resource_changes`
  - `metric_points`
  - `cost_usage`
  - `advisor_recommendations`
  - `entra_directory_audits`
  - `entra_signins`
  - `ingestion_runs`
  - `ingestion_checkpoints`
  - `raw_payloads`
  - `collector_schedules`
- Job orchestration with distinct scheduler and worker loops
- Per-source interval configuration
- Per-source concurrency limiting in the worker claim path
- Checkpoint persistence
- Raw payload persistence for replay and audit
- Idempotent upsert patterns for the implemented collectors
- Soft-delete behavior for snapshot resources no longer present
- REST APIs for onboarding, credentials, sources, schedules, runs, resources, activity events, and raw payload replay

### Implemented collectors

- `resource_graph`
  - subscription discovery
  - Azure Resource Graph paging via `skipToken`
  - normalized inventory storage
  - `resources_current` upsert
  - `resources_history` change rows
  - soft-delete marking for missing resources
- `activity_log`
  - per-subscription incremental polling
  - `nextLink` continuation handling
  - normalized `activity_events`
  - per-subscription checkpoints

### Registered but placeholder collectors

- `change_analysis`
- `metrics`
- `cost_exports`
- `cost_query`
- `advisor`
- `entra_directory_audits`
- `entra_signins`

## Configuration

Key environment variables:

- `DATABASE_URL`
- `PLATFORM_ENTRA_CLIENT_ID`
- `PLATFORM_ENTRA_CLIENT_SECRET`
- `PLATFORM_ENTRA_REDIRECT_URI`
- `PLATFORM_ENCRYPTION_KEY`
- `COLLECTOR_INTERVALS_MINUTES_JSON`
- `SOURCE_CONCURRENCY_LIMITS_JSON`
- `SCHEDULER_POLL_SECONDS`
- `WORKER_POLL_SECONDS`

## Local Run

### 1. Start the stack

```bash
cd azure_ingestion_platform
docker compose up --build
```

The web API will be available at `http://localhost:8081`.

### 2. Onboard a tenant

```bash
curl -X POST http://localhost:8081/api/v1/tenants/onboarding \
  -H 'content-type: application/json' \
  -d '{
    "slug": "contoso",
    "display_name": "Contoso",
    "tenant_external_id": "00000000-0000-0000-0000-000000000000"
  }'
```

Open the returned `consent_url`, complete admin consent, then let Entra redirect back to `/api/v1/onboarding/callback`.

### 3. Queue a collector run

```bash
curl -X POST http://localhost:8081/api/v1/tenants/<tenant-id>/runs \
  -H 'content-type: application/json' \
  -d '{"source":"resource_graph","subscription_ids":[]}'
```

### 4. Inspect data

```bash
curl http://localhost:8081/api/v1/resources/current
curl http://localhost:8081/api/v1/activity-events
curl http://localhost:8081/api/v1/raw-payloads
```

## Tests

Run the focused test suite with the repo virtualenv:

```bash
cd /workspace/altlassian
DATABASE_URL=sqlite+pysqlite:///./azure_ingestion_platform_test.db \
  ./.venv/bin/pytest -q azure_ingestion_platform/tests
```

## Notes

- This is a starter production architecture, not a finished ingest matrix for every Azure source yet.
- The plugin registry is in place so additional collectors can be added without changing the scheduler or worker contract.
- The onboarding flow uses admin consent with platform-wide app credentials by default, plus optional per-tenant encrypted client-secret overrides for dedicated app registrations.
- For true horizontal production scaling, the next hardening step would be stronger cross-worker distributed source limits and richer telemetry export to Prometheus/OpenTelemetry.
