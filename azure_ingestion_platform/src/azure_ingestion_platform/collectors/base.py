from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from ..azure import AzureApiClient
from ..models import IngestionCheckpoint, IngestionRun, Tenant


@dataclass(slots=True)
class CollectorResult:
    source: str
    status: str
    stats: dict[str, Any] = field(default_factory=dict)
    checkpoints: list[tuple[str, str, str, dict[str, Any]]] = field(default_factory=list)


@dataclass(slots=True)
class CollectorContext:
    db: Session
    tenant: Tenant
    run: IngestionRun
    client: AzureApiClient
    checkpoint_map: dict[str, IngestionCheckpoint]
    now: datetime


class CollectorPlugin(Protocol):
    source: str
    kind: str
    description: str
    implemented: bool

    def default_interval_minutes(self) -> int: ...

    def collect(self, context: CollectorContext) -> CollectorResult: ...
