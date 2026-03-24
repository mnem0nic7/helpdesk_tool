from __future__ import annotations

import logging
import socket
import time
from datetime import datetime, timezone

from sqlalchemy import select

from ..azure import AzureApiClient
from ..collectors.base import CollectorContext
from ..collectors.registry import build_registry
from ..config import settings
from ..db import session_scope
from ..models import IngestionRun, Tenant
from .jobs import claim_next_run, finish_run, load_checkpoints, save_checkpoints

logger = logging.getLogger(__name__)


def run_worker_forever() -> None:
    registry = build_registry()
    worker_id = socket.gethostname()
    while True:
        claimed = False
        active_run_id = ""
        try:
            with session_scope() as db:
                run = claim_next_run(db, worker_id=worker_id)
                if run is None:
                    pass
                else:
                    claimed = True
                    active_run_id = run.id
                    tenant = db.execute(select(Tenant).where(Tenant.id == run.tenant_id)).scalar_one()
                    collector = registry[run.source]
                    client = AzureApiClient(db, tenant)
                    checkpoints = load_checkpoints(db, tenant.id, run.source)
                    context = CollectorContext(
                        db=db,
                        tenant=tenant,
                        run=run,
                        client=client,
                        checkpoint_map=checkpoints,
                        now=datetime.now(timezone.utc),
                    )
                    result = collector.collect(context)
                    save_checkpoints(db, tenant.id, result.checkpoints)
                    finish_run(db, run, status=result.status, stats_json=result.stats)
        except Exception as exc:
            logger.exception("Worker loop failed")
            try:
                with session_scope() as db:
                    run = db.execute(select(IngestionRun).where(IngestionRun.id == active_run_id)).scalar_one_or_none()
                    if run is not None:
                        finish_run(db, run, status="failed", error_text=str(exc))
            except Exception:
                logger.exception("Failed to record worker error")
        time.sleep(1 if claimed else settings.worker_poll_seconds)
