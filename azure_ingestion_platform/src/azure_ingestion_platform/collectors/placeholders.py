from __future__ import annotations

from .base import CollectorContext, CollectorPlugin, CollectorResult


class PlaceholderCollector(CollectorPlugin):
    def __init__(self, source: str, description: str, interval_minutes: int) -> None:
        self.source = source
        self.kind = "placeholder"
        self.description = description
        self._interval_minutes = interval_minutes
        self.implemented = False

    def default_interval_minutes(self) -> int:
        return self._interval_minutes

    def collect(self, context: CollectorContext) -> CollectorResult:
        raise NotImplementedError(f"{self.source} is not implemented yet")
