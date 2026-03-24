from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from ..collectors.registry import build_registry
from ..config import settings
from ..db import session_scope
from .jobs import due_schedules, enqueue_run

logger = logging.getLogger(__name__)


def run_scheduler_forever() -> None:
    registry = build_registry()
    while True:
        try:
            with session_scope() as db:
                for tenant, schedule in due_schedules(db):
                    collector = registry[schedule.source]
                    enqueue_run(
                        db,
                        tenant_id=tenant.id,
                        source=schedule.source,
                        collector=collector.__class__.__name__,
                        scope_json=schedule.scope_json,
                    )
                    schedule.last_enqueued_at = datetime.now(timezone.utc)
                    logger.info("Enqueued %s for tenant %s", schedule.source, tenant.slug)
        except Exception:
            logger.exception("Scheduler loop failed")
        time.sleep(settings.scheduler_poll_seconds)
