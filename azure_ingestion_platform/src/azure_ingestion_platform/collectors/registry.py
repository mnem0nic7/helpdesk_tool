from __future__ import annotations

from .activity_log import ActivityLogCollector
from .base import CollectorPlugin
from .placeholders import PlaceholderCollector
from .resource_graph import ResourceGraphCollector


def build_registry() -> dict[str, CollectorPlugin]:
    collectors: list[CollectorPlugin] = [
        ResourceGraphCollector(),
        ActivityLogCollector(),
        PlaceholderCollector("change_analysis", "Azure Resource Graph Change Analysis deltas.", 15),
        PlaceholderCollector("metrics", "Azure Monitor Metrics bundles by resource type.", 15),
        PlaceholderCollector("cost_exports", "Azure Cost Management export discovery and pull.", 360),
        PlaceholderCollector("cost_query", "Azure Cost Management query drilldowns.", 120),
        PlaceholderCollector("advisor", "Azure Advisor recommendation ingestion.", 720),
        PlaceholderCollector("entra_directory_audits", "Microsoft Graph directory audit logs.", 15),
        PlaceholderCollector("entra_signins", "Microsoft Graph sign-in log ingestion.", 15),
    ]
    return {collector.source: collector for collector in collectors}
