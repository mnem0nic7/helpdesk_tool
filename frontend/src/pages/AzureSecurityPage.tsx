import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import AzureSourceBadge from "../components/AzureSourceBadge.tsx";
import {
  AzureSecurityLaneActionButton,
  azureSecurityToneClasses,
  type AzureSecurityLaneAction,
  type AzureSecurityLaneTone,
} from "../components/AzureSecurityLane.tsx";
import { api, type SecurityWorkspaceLaneSummary } from "../lib/api.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";

type LaneGroup = "respond-now" | "identity-app-control" | "accounts-external-access" | "devices-posture";
type GroupFilter = "all" | LaneGroup;
type LaneStateFilter = "all" | "needs-attention" | "healthy-available" | "limited-access";

type LaneCatalogItem = {
  key: string;
  group: LaneGroup;
  title: string;
  description: string;
  keywords: string[];
  actions: AzureSecurityLaneAction[];
  fallbackAttentionLabel: string;
  fallbackSecondaryLabel: string;
  summaryMode: SecurityWorkspaceLaneSummary["summary_mode"];
};

type SupportCardDefinition = {
  eyebrow: string;
  title: string;
  description: string;
  actions: AzureSecurityLaneAction[];
};

type PersistedWorkspaceView = {
  search: string;
  groupFilter: GroupFilter;
  stateFilter: LaneStateFilter;
  roadmapOpen: boolean;
  collapsedGroups: Record<LaneGroup, boolean>;
};

const INITIAL_GROUP_COLLAPSE_STATE: Record<LaneGroup, boolean> = {
  "respond-now": false,
  "identity-app-control": false,
  "accounts-external-access": false,
  "devices-posture": false,
};

const SECURITY_WORKSPACE_VIEW_STORAGE_KEY = "azureSecurityWorkspaceView";

const GROUP_LABELS: Record<LaneGroup, string> = {
  "respond-now": "Respond Now",
  "identity-app-control": "Identity & App Control",
  "accounts-external-access": "Accounts & External Access",
  "devices-posture": "Devices & Posture",
};

const GROUP_OPTIONS: Array<{ value: GroupFilter; label: string }> = [
  { value: "all", label: "All groups" },
  { value: "respond-now", label: "Respond Now" },
  { value: "identity-app-control", label: "Identity & App Control" },
  { value: "accounts-external-access", label: "Accounts & External Access" },
  { value: "devices-posture", label: "Devices & Posture" },
];

const STATE_OPTIONS: Array<{ value: LaneStateFilter; label: string }> = [
  { value: "all", label: "All states" },
  { value: "needs-attention", label: "Needs attention" },
  { value: "healthy-available", label: "Healthy/available" },
  { value: "limited-access", label: "Limited access" },
];

const LANE_CATALOG: LaneCatalogItem[] = [
  {
    key: "defender-agent",
    group: "respond-now",
    title: "Autonomous Defender Agent",
    description:
      "Polls Microsoft Defender alerts every 2 minutes. Auto-revokes sessions and syncs devices for T1 detections. Queues sign-in disables with a cancellation window (T2). Surfaces device wipe and retire for human approval (T3).",
    keywords: ["defender", "agent", "autonomous", "remediation", "alert", "session", "revoke", "disable", "wipe"],
    actions: [
      { label: "Open Agent Console", to: "/security/agent" },
    ],
    fallbackAttentionLabel: "Agent disabled — click to configure",
    fallbackSecondaryLabel: "Enable the agent to start autonomous Defender alert response.",
    summaryMode: "count",
  },
  {
    key: "security-copilot",
    group: "respond-now",
    title: "Security Incident Copilot",
    description:
      "Run guided incident intake, fill evidence gaps with grounded Azure and local context, and export a repeatable investigation handoff.",
    keywords: ["copilot", "incident", "alerts", "investigation", "response", "mailbox"],
    actions: [
      { label: "Open Security Copilot", to: "/security/copilot" },
      { label: "Open Azure Alerts", to: "/alerts", tone: "secondary" },
    ],
    fallbackAttentionLabel: "Ready for investigation",
    fallbackSecondaryLabel: "Open the copilot to start guided incident intake.",
    summaryMode: "manual",
  },
  {
    key: "dlp-review",
    group: "respond-now",
    title: "DLP Findings Review",
    description:
      "Paste a Purview-style finding, normalize actors and destinations, and review grounded identity and mailbox context before escalation.",
    keywords: ["dlp", "purview", "finding", "exfiltration", "mailbox", "review"],
    actions: [
      { label: "Open DLP Findings Review", to: "/security/dlp-review" },
      { label: "Open Security Copilot", to: "/security/copilot", tone: "secondary" },
    ],
    fallbackAttentionLabel: "Ready for pasted findings",
    fallbackSecondaryLabel: "Manual lane for pasted DLP incidents and escalation prep.",
    summaryMode: "manual",
  },
  {
    key: "access-review",
    group: "respond-now",
    title: "Privileged Access Review",
    description:
      "Review elevated Azure RBAC assignments, risky guest or stale privileged accounts, and break-glass watchlists from one lane.",
    keywords: ["rbac", "privileged", "owner", "contributor", "subscription", "break-glass"],
    actions: [
      { label: "Open Access Review", to: "/security/access-review" },
      { label: "Open Break-glass Validation", to: "/security/break-glass-validation", tone: "secondary" },
    ],
    fallbackAttentionLabel: "Open privileged access review",
    fallbackSecondaryLabel: "Review elevated RBAC principals and assignments.",
    summaryMode: "count",
  },
  {
    key: "conditional-access-tracker",
    group: "respond-now",
    title: "Conditional Access Change Tracker",
    description:
      "Track broad-scope policy drift, recent add or update operations, and exclusion surfaces before they turn into user-impacting outages.",
    keywords: ["conditional access", "policy", "drift", "mfa", "exceptions", "audit"],
    actions: [
      { label: "Open Conditional Access Tracker", to: "/security/conditional-access-tracker" },
      { label: "Open Security Copilot", to: "/security/copilot", tone: "secondary" },
    ],
    fallbackAttentionLabel: "Open policy drift review",
    fallbackSecondaryLabel: "Review cached policy posture and recent changes.",
    summaryMode: "count",
  },
  {
    key: "break-glass-validation",
    group: "identity-app-control",
    title: "Break-glass Account Validation",
    description:
      "Validate likely emergency accounts against sign-in freshness, password age, sync source, licensing, and Azure RBAC exposure.",
    keywords: ["break-glass", "emergency", "tier 0", "admin", "password", "sign-in"],
    actions: [
      { label: "Open Break-glass Validation", to: "/security/break-glass-validation" },
      { label: "Open Access Review", to: "/security/access-review", tone: "secondary" },
    ],
    fallbackAttentionLabel: "Open emergency account validation",
    fallbackSecondaryLabel: "Check freshness, licensing, and emergency-account readiness.",
    summaryMode: "count",
  },
  {
    key: "identity-review",
    group: "identity-app-control",
    title: "Identity Review",
    description:
      "Review groups, enterprise applications, app registrations, and directory roles from one security-first lane before drilling into raw inventory.",
    keywords: ["identity", "groups", "app registrations", "enterprise apps", "directory roles", "owners"],
    actions: [
      { label: "Open Identity Review", to: "/security/identity-review" },
      { label: "Open Directory Role Review", to: "/security/directory-role-review", tone: "secondary" },
    ],
    fallbackAttentionLabel: "Open identity review",
    fallbackSecondaryLabel: "Review app owner gaps, external audience exposure, and role posture.",
    summaryMode: "count",
  },
  {
    key: "directory-role-review",
    group: "identity-app-control",
    title: "Directory Role Membership Review",
    description:
      "Review live direct Entra directory-role memberships, then ground flagged users, groups, and service principals against cached context.",
    keywords: ["directory role", "entra", "global administrator", "role membership", "direct role"],
    actions: [
      { label: "Open Directory Role Review", to: "/security/directory-role-review" },
      { label: "Open Identity Review", to: "/security/identity-review", tone: "secondary" },
    ],
    fallbackAttentionLabel: "Live review available from the lane",
    fallbackSecondaryLabel: "Availability-only summary; detailed membership loads when opened.",
    summaryMode: "availability",
  },
  {
    key: "app-hygiene",
    group: "identity-app-control",
    title: "Application Hygiene",
    description:
      "Review app owner coverage, expiring secrets and certificates, external audience exposure, and publisher trust from one lane.",
    keywords: ["application hygiene", "credentials", "secret", "certificate", "owners", "publisher"],
    actions: [
      { label: "Open Application Hygiene", to: "/security/app-hygiene" },
      { label: "Open Identity Review", to: "/security/identity-review", tone: "secondary" },
    ],
    fallbackAttentionLabel: "Open application hygiene",
    fallbackSecondaryLabel: "Review app credentials, owner gaps, and external exposure.",
    summaryMode: "count",
  },
  {
    key: "user-review",
    group: "accounts-external-access",
    title: "User Review",
    description:
      "Work stale sign-ins, disabled licensed accounts, guest identities, synced users, and shared/service-style accounts from one review lane.",
    keywords: ["users", "priority queue", "stale sign-in", "disabled", "licensed", "shared service"],
    actions: [
      { label: "Open User Review", to: "/security/user-review" },
      { label: "Open Account Health", to: "/security/account-health", tone: "secondary" },
    ],
    fallbackAttentionLabel: "Open user review",
    fallbackSecondaryLabel: "Review priority users and stale sign-in posture.",
    summaryMode: "count",
  },
  {
    key: "guest-access-review",
    group: "accounts-external-access",
    title: "Guest Access Review",
    description:
      "Review guest identities, collaboration groups that can widen external reach, and app registrations that allow identities from outside the tenant.",
    keywords: ["guest", "external", "collaboration", "m365", "sharing", "b2b"],
    actions: [
      { label: "Open Guest Access Review", to: "/security/guest-access-review" },
      { label: "Open User Review", to: "/security/user-review", tone: "secondary" },
    ],
    fallbackAttentionLabel: "Open guest-access review",
    fallbackSecondaryLabel: "Review old guests, stale guests, and external reach surfaces.",
    summaryMode: "count",
  },
  {
    key: "account-health",
    group: "accounts-external-access",
    title: "Account Health",
    description:
      "Review disabled accounts, stale cloud passwords, old guest identities, and incomplete employee profiles from one hygiene lane.",
    keywords: ["account health", "stale password", "disabled account", "guest age", "profile completeness"],
    actions: [
      { label: "Open Account Health", to: "/security/account-health" },
      { label: "Open User Review", to: "/security/user-review", tone: "secondary" },
    ],
    fallbackAttentionLabel: "Open account hygiene review",
    fallbackSecondaryLabel: "Review passwords, disabled accounts, guests, and profile gaps.",
    summaryMode: "count",
  },
  {
    key: "device-compliance",
    group: "devices-posture",
    title: "Device Compliance Review",
    description:
      "Review tenant-wide Intune managed-device posture, stale sync, missing primary users, risky personal devices, and remediation readiness.",
    keywords: ["device", "intune", "compliance", "stale sync", "primary user", "retire"],
    actions: [
      { label: "Open Device Compliance Review", to: "/security/device-compliance" },
      { label: "Open User Review", to: "/security/user-review", tone: "secondary" },
    ],
    fallbackAttentionLabel: "Open device posture review",
    fallbackSecondaryLabel: "Review noncompliant, stale, and ownerless managed devices.",
    summaryMode: "count",
  },
];

const SUPPORT_TOOLS: SupportCardDefinition[] = [
  {
    eyebrow: "Support Tool",
    title: "Detection and Response",
    description: "Pivot into alerts, Defender, and the Azure portal when a review lane needs deeper telemetry or live remediation.",
    actions: [
      { label: "Azure Alerts", to: "/alerts" },
      { label: "Microsoft Defender", to: "https://security.microsoft.com/", external: true, tone: "secondary" },
      { label: "Azure Portal", to: "https://portal.azure.com/", external: true, tone: "secondary" },
    ],
  },
  {
    eyebrow: "Support Tool",
    title: "Operator Consoles",
    description: "Use shared admin tooling and Entra console pivots when a review turns into tenant administration or hands-on change work.",
    actions: [
      { label: "Shared Admin Tools", to: "/tools" },
      { label: "Entra Admin Center", to: "https://entra.microsoft.com/", external: true, tone: "secondary" },
      { label: "Azure Overview", to: "/", tone: "secondary" },
    ],
  },
];

function buildDefaultWorkspaceView(): PersistedWorkspaceView {
  return {
    search: "",
    groupFilter: "all",
    stateFilter: "all",
    roadmapOpen: false,
    collapsedGroups: { ...INITIAL_GROUP_COLLAPSE_STATE },
  };
}

function isLaneGroup(value: string): value is LaneGroup {
  return value in GROUP_LABELS;
}

function isGroupFilter(value: string): value is GroupFilter {
  return value === "all" || isLaneGroup(value);
}

function isLaneStateFilter(value: string): value is LaneStateFilter {
  return STATE_OPTIONS.some((option) => option.value === value);
}

function readPersistedWorkspaceView(): PersistedWorkspaceView {
  const fallback = buildDefaultWorkspaceView();
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(SECURITY_WORKSPACE_VIEW_STORAGE_KEY);
    if (!raw) return fallback;

    const parsed = JSON.parse(raw) as Partial<PersistedWorkspaceView>;
    const collapsedGroups = { ...INITIAL_GROUP_COLLAPSE_STATE };
    const persistedCollapsedGroups = parsed.collapsedGroups;
    if (persistedCollapsedGroups && typeof persistedCollapsedGroups === "object") {
      (Object.keys(INITIAL_GROUP_COLLAPSE_STATE) as LaneGroup[]).forEach((group) => {
        const value = persistedCollapsedGroups[group];
        if (typeof value === "boolean") collapsedGroups[group] = value;
      });
    }

    return {
      search: typeof parsed.search === "string" ? parsed.search : fallback.search,
      groupFilter: typeof parsed.groupFilter === "string" && isGroupFilter(parsed.groupFilter) ? parsed.groupFilter : fallback.groupFilter,
      stateFilter: typeof parsed.stateFilter === "string" && isLaneStateFilter(parsed.stateFilter) ? parsed.stateFilter : fallback.stateFilter,
      roadmapOpen: parsed.roadmapOpen === true,
      collapsedGroups,
    };
  } catch {
    return fallback;
  }
}

function persistWorkspaceView(view: PersistedWorkspaceView): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SECURITY_WORKSPACE_VIEW_STORAGE_KEY, JSON.stringify(view));
  } catch {
    // Ignore storage failures so the workspace stays usable in restricted browsers.
  }
}

function clearPersistedWorkspaceView(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(SECURITY_WORKSPACE_VIEW_STORAGE_KEY);
  } catch {
    // Ignore storage failures so reset still updates the in-memory view.
  }
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "No refresh recorded yet";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function toneForStatus(status: SecurityWorkspaceLaneSummary["status"]): AzureSecurityLaneTone {
  if (status === "critical") return "rose";
  if (status === "warning" || status === "unavailable") return "amber";
  if (status === "healthy") return "emerald";
  return "sky";
}

function statusLabel(status: SecurityWorkspaceLaneSummary["status"]): string {
  if (status === "critical") return "Critical";
  if (status === "warning") return "Needs attention";
  if (status === "healthy") return "Healthy";
  if (status === "unavailable") return "Limited access";
  return "Ready";
}

function fallbackSummary(item: LaneCatalogItem, refreshAt: string): SecurityWorkspaceLaneSummary {
  return {
    lane_key: item.key,
    status: item.summaryMode === "manual" ? "info" : "info",
    attention_score: 0,
    attention_count: 0,
    attention_label: item.fallbackAttentionLabel,
    secondary_label: item.fallbackSecondaryLabel,
    refresh_at: refreshAt,
    access_available: true,
    access_message: "",
    warning_count: 0,
    summary_mode: item.summaryMode,
  };
}

function laneMatchesSearch(item: LaneCatalogItem, search: string): boolean {
  if (!search) return true;
  const haystack = [item.title, item.description, GROUP_LABELS[item.group], ...item.keywords].join(" ").toLowerCase();
  return haystack.includes(search.toLowerCase());
}

function laneMatchesState(summary: SecurityWorkspaceLaneSummary, stateFilter: LaneStateFilter): boolean {
  if (stateFilter === "all") return true;
  if (stateFilter === "needs-attention") return summary.status === "critical" || summary.status === "warning";
  if (stateFilter === "healthy-available") return summary.status === "healthy" || summary.status === "info";
  return summary.status === "unavailable";
}

function isAttentionStatus(status: SecurityWorkspaceLaneSummary["status"]): boolean {
  return status === "critical" || status === "warning" || status === "unavailable";
}

function countAttentionItems(items: Array<{ summary: SecurityWorkspaceLaneSummary }>): number {
  return items.filter(({ summary }) => isAttentionStatus(summary.status)).length;
}

function LaneStatusPill({ summary }: { summary: SecurityWorkspaceLaneSummary }) {
  return <span className={`rounded-full px-3 py-1 text-xs font-semibold ${azureSecurityToneClasses(toneForStatus(summary.status))}`}>{statusLabel(summary.status)}</span>;
}

function LaneCard({
  item,
  summary,
}: {
  item: LaneCatalogItem;
  summary: SecurityWorkspaceLaneSummary;
}) {
  const tone = toneForStatus(summary.status);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{GROUP_LABELS[item.group]}</div>
        <LaneStatusPill summary={summary} />
      </div>
      <h3 className="mt-3 text-lg font-semibold text-slate-900">{item.title}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{item.description}</p>

      <div className={`mt-4 rounded-2xl border px-4 py-4 ${tone === "rose" ? "border-rose-200 bg-rose-50/60" : tone === "amber" ? "border-amber-200 bg-amber-50/60" : tone === "emerald" ? "border-emerald-200 bg-emerald-50/60" : "border-sky-200 bg-sky-50/60"}`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              {summary.attention_count > 0 ? (
                <div className={tone === "rose" ? "text-2xl font-semibold text-rose-700" : tone === "amber" ? "text-2xl font-semibold text-amber-700" : "text-2xl font-semibold text-sky-700"}>
                  {summary.attention_count.toLocaleString()}
                </div>
              ) : null}
              <div className="text-sm font-semibold text-slate-900">{summary.attention_label}</div>
            </div>
            <p className="mt-2 text-sm leading-6 text-slate-600">{summary.secondary_label}</p>
            {summary.access_available ? null : (
              <div className="mt-3 rounded-xl bg-white/80 px-3 py-2 text-sm text-amber-900">{summary.access_message}</div>
            )}
          </div>
          <div className="rounded-xl border border-white/80 bg-white/90 px-3 py-2 text-right text-xs text-slate-500">
            <div className="font-semibold uppercase tracking-wide text-slate-400">Refresh</div>
            <div className="mt-1 text-sm font-medium text-slate-900">{formatTimestamp(summary.refresh_at)}</div>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2 text-xs">
          <span className="rounded-full bg-white/90 px-3 py-1 font-semibold text-slate-700">{summary.summary_mode === "manual" ? "Manual lane" : summary.summary_mode === "availability" ? "Availability summary" : "Live summary"}</span>
          {summary.warning_count > 0 ? (
            <span className="rounded-full bg-white/90 px-3 py-1 font-semibold text-amber-800">{summary.warning_count.toLocaleString()} cache warning{summary.warning_count === 1 ? "" : "s"}</span>
          ) : null}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {item.actions.map((action) => (
          <AzureSecurityLaneActionButton key={`${item.key}-${action.label}`} action={action} />
        ))}
      </div>
    </section>
  );
}

function PriorityLaneCard({
  item,
  summary,
}: {
  item: LaneCatalogItem;
  summary: SecurityWorkspaceLaneSummary;
}) {
  const tone = toneForStatus(summary.status);
  const backgroundClass =
    tone === "rose"
      ? "from-white via-rose-50 to-slate-50"
      : tone === "amber"
        ? "from-white via-amber-50 to-orange-50"
        : "from-white via-sky-50 to-slate-50";

  return (
    <section className={`rounded-2xl border border-slate-200 bg-gradient-to-br ${backgroundClass} p-5 shadow-sm`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{GROUP_LABELS[item.group]}</div>
        <LaneStatusPill summary={summary} />
      </div>
      <h3 className="mt-3 text-lg font-semibold text-slate-900">{item.title}</h3>
      <div className="mt-4 flex items-end gap-3">
        {summary.attention_count > 0 ? (
          <div className={tone === "rose" ? "text-4xl font-semibold text-rose-700" : "text-4xl font-semibold text-amber-700"}>{summary.attention_count.toLocaleString()}</div>
        ) : null}
        <div className="pb-1 text-sm font-medium text-slate-700">{summary.attention_label}</div>
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-600">{summary.secondary_label}</p>
      {summary.access_available ? null : (
        <div className="mt-3 rounded-xl border border-amber-200 bg-white/85 px-3 py-2 text-sm text-amber-900">{summary.access_message}</div>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        {item.actions.slice(0, 2).map((action) => (
          <AzureSecurityLaneActionButton key={`${item.key}-priority-${action.label}`} action={action} />
        ))}
      </div>
    </section>
  );
}

function SupportCard({ card }: { card: SupportCardDefinition }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{card.eyebrow}</div>
      <h3 className="mt-3 text-lg font-semibold text-slate-900">{card.title}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{card.description}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {card.actions.map((action) => (
          <AzureSecurityLaneActionButton key={`${card.title}-${action.label}`} action={action} />
        ))}
      </div>
    </section>
  );
}

export default function AzureSecurityPage() {
  const initialWorkspaceView = useMemo(() => readPersistedWorkspaceView(), []);
  const [search, setSearch] = useState(initialWorkspaceView.search);
  const [groupFilter, setGroupFilter] = useState<GroupFilter>(initialWorkspaceView.groupFilter);
  const [stateFilter, setStateFilter] = useState<LaneStateFilter>(initialWorkspaceView.stateFilter);
  const [roadmapOpen, setRoadmapOpen] = useState(initialWorkspaceView.roadmapOpen);
  const [collapsedGroups, setCollapsedGroups] = useState<Record<LaneGroup, boolean>>(initialWorkspaceView.collapsedGroups);
  const deferredSearch = useDeferredValue(search);
  const normalizedSearch = search.trim();
  const normalizedDeferredSearch = deferredSearch.trim();

  const overviewQuery = useQuery({
    queryKey: ["azure", "overview"],
    queryFn: () => api.getAzureOverview(),
    ...getPollingQueryOptions("slow_5m"),
  });
  const statusQuery = useQuery({
    queryKey: ["azure", "status"],
    queryFn: () => api.getAzureStatus(),
    ...getPollingQueryOptions("slow_5m"),
  });
  const summaryQuery = useQuery({
    queryKey: ["azure", "security", "workspace-summary"],
    queryFn: () => api.getAzureSecurityWorkspaceSummary(),
    ...getPollingQueryOptions("slow_5m"),
  });

  const overview = overviewQuery.data;
  const status = statusQuery.data;
  const datasets = status?.datasets ?? overview?.datasets ?? [];
  const configuredDatasetCount = datasets.filter((dataset) => dataset.configured).length;
  const healthyDatasetCount = datasets.filter((dataset) => dataset.configured && !dataset.error).length;
  const datasetLabel = configuredDatasetCount
    ? `${healthyDatasetCount}/${configuredDatasetCount} configured datasets healthy`
    : "No configured datasets yet";
  const datasetTone = configuredDatasetCount > 0 && healthyDatasetCount === configuredDatasetCount ? "emerald" : "amber";
  const sharedRefresh = status?.last_refresh ?? overview?.last_refresh ?? "";
  const summaryRefresh = summaryQuery.data?.workspace_last_refresh ?? sharedRefresh;
  const summaryMap = new Map(summaryQuery.data?.lanes.map((lane) => [lane.lane_key, lane]));

  const mergedLanes = useMemo(
    () =>
      LANE_CATALOG.map((item, index) => ({
        item,
        summary: summaryMap.get(item.key) ?? fallbackSummary(item, summaryRefresh ?? ""),
        staticOrder: index,
      })),
    [summaryMap, summaryRefresh],
  );

  const priorityLanes = useMemo(
    () =>
      [...mergedLanes]
        .filter(({ summary }) => summary.status === "critical" || summary.status === "warning" || summary.status === "unavailable")
        .filter(({ summary }) => !(summary.summary_mode === "manual" && summary.status !== "unavailable"))
        .sort((left, right) => right.summary.attention_score - left.summary.attention_score || left.staticOrder - right.staticOrder)
        .slice(0, 4),
    [mergedLanes],
  );

  const filteredLanes = useMemo(
    () =>
      mergedLanes.filter(({ item, summary }) => {
        if (groupFilter !== "all" && item.group !== groupFilter) return false;
        if (!laneMatchesState(summary, stateFilter)) return false;
        return laneMatchesSearch(item, normalizedDeferredSearch);
      }),
    [groupFilter, mergedLanes, normalizedDeferredSearch, stateFilter],
  );

  const groupedLanes = useMemo(
    () =>
      GROUP_OPTIONS.filter((option) => option.value !== "all")
        .map((option) => ({
          key: option.value as LaneGroup,
          label: option.label,
          items: [...filteredLanes]
            .filter(({ item }) => item.group === option.value)
            .sort((left, right) => right.summary.attention_score - left.summary.attention_score || left.staticOrder - right.staticOrder),
        }))
        .filter((group) => group.items.length > 0),
    [filteredLanes],
  );

  const groupOptionCounts = useMemo(() => {
    const counts: Record<GroupFilter, number> = {
      all: 0,
      "respond-now": 0,
      "identity-app-control": 0,
      "accounts-external-access": 0,
      "devices-posture": 0,
    };

    mergedLanes.forEach(({ item, summary }) => {
      if (!laneMatchesState(summary, stateFilter)) return;
      if (!laneMatchesSearch(item, normalizedDeferredSearch)) return;
      counts.all += 1;
      counts[item.group] += 1;
    });

    return counts;
  }, [mergedLanes, normalizedDeferredSearch, stateFilter]);

  const stateOptionCounts = useMemo(() => {
    const counts: Record<LaneStateFilter, number> = {
      all: 0,
      "needs-attention": 0,
      "healthy-available": 0,
      "limited-access": 0,
    };

    mergedLanes.forEach(({ item, summary }) => {
      if (groupFilter !== "all" && item.group !== groupFilter) return;
      if (!laneMatchesSearch(item, normalizedDeferredSearch)) return;
      counts.all += 1;
      if (laneMatchesState(summary, "needs-attention")) counts["needs-attention"] += 1;
      if (laneMatchesState(summary, "healthy-available")) counts["healthy-available"] += 1;
      if (laneMatchesState(summary, "limited-access")) counts["limited-access"] += 1;
    });

    return counts;
  }, [groupFilter, mergedLanes, normalizedDeferredSearch]);

  const hasActiveFilters = normalizedSearch.length > 0 || groupFilter !== "all" || stateFilter !== "all";
  const hasNonDefaultView = hasActiveFilters || roadmapOpen || Object.values(collapsedGroups).some(Boolean);

  useEffect(() => {
    persistWorkspaceView({
      search,
      groupFilter,
      stateFilter,
      roadmapOpen,
      collapsedGroups,
    });
  }, [collapsedGroups, groupFilter, roadmapOpen, search, stateFilter]);

  if (overviewQuery.isLoading) {
    return <AzurePageSkeleton titleWidth="w-56" subtitleWidth="w-[40rem]" statCount={4} sectionCount={4} />;
  }

  if (overviewQuery.isError || !overview) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load Azure security workspace: {overviewQuery.error instanceof Error ? overviewQuery.error.message : "Unknown error"}
      </div>
    );
  }

  const clearAllFilters = () => {
    setSearch("");
    setGroupFilter("all");
    setStateFilter("all");
  };

  const restoreDefaultView = () => {
    const defaults = buildDefaultWorkspaceView();
    clearPersistedWorkspaceView();
    setSearch(defaults.search);
    setGroupFilter(defaults.groupFilter);
    setStateFilter(defaults.stateFilter);
    setRoadmapOpen(defaults.roadmapOpen);
    setCollapsedGroups(defaults.collapsedGroups);
  };


  const toggleGroupCollapsed = (group: LaneGroup) => {
    setCollapsedGroups((current) => ({
      ...current,
      [group]: !current[group],
    }));
  };

  const setAllVisibleGroupsCollapsed = (collapsed: boolean) => {
    setCollapsedGroups((current) => {
      const next = { ...current };
      groupedLanes.forEach((group) => {
        next[group.key] = collapsed;
      });
      return next;
    });
  };

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Azure Security</h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">
            Triage-first workspace for Azure review lanes, incident response, and tenant hygiene.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <AzureSourceBadge
              label={status?.refreshing ? "Azure refresh in progress" : "Azure cache ready"}
              description={`Latest Azure refresh: ${formatTimestamp(sharedRefresh)}`}
              tone={status?.refreshing ? "amber" : "emerald"}
            />
            <AzureSourceBadge
              label={datasetLabel}
              description="Configured dataset health for the Azure security workspace."
              tone={datasetTone}
            />
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <AzureSecurityLaneActionButton action={{ label: "Security Copilot", to: "/security/copilot" }} />
          <AzureSecurityLaneActionButton action={{ label: "Azure Alerts", to: "/alerts", tone: "secondary" }} />
        </div>
      </div>

      {summaryQuery.isError ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Live lane summaries are temporarily unavailable — showing the static workspace catalog.
        </div>
      ) : null}

      {/* Needs Attention */}
      {priorityLanes.length > 0 ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-base font-semibold text-slate-900">Needs Attention Now</h2>
          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            {priorityLanes.map(({ item, summary }) => (
              <PriorityLaneCard key={`priority-${item.key}`} item={item} summary={summary} />
            ))}
          </div>
        </section>
      ) : null}

      {/* Filter bar + catalog */}
      <section className="space-y-3">
        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search lanes — incidents, privileged access, guests, devices, apps..."
              className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-sky-500"
            />
            {hasActiveFilters ? (
              <button type="button" onClick={clearAllFilters} className="rounded-full border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100">
                Clear
              </button>
            ) : null}
            {hasNonDefaultView ? (
              <button type="button" onClick={restoreDefaultView} className="rounded-full border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100">
                Reset view
              </button>
            ) : null}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-6 gap-y-2">
            <div className="flex flex-wrap gap-1.5">
              {GROUP_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setGroupFilter(option.value)}
                  aria-pressed={groupFilter === option.value}
                  className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${groupFilter === option.value ? "bg-sky-700 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
                >
                  {option.label}
                  <span className={`ml-1.5 rounded-full px-1.5 py-0.5 text-[10px] ${groupFilter === option.value ? "bg-white/20 text-white" : "bg-white text-slate-500"}`}>
                    {groupOptionCounts[option.value]}
                  </span>
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {STATE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setStateFilter(option.value)}
                  aria-pressed={stateFilter === option.value}
                  className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${stateFilter === option.value ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
                >
                  {option.label}
                  <span className={`ml-1.5 rounded-full px-1.5 py-0.5 text-[10px] ${stateFilter === option.value ? "bg-white/15 text-white" : "bg-white text-slate-500"}`}>
                    {stateOptionCounts[option.value]}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Grouped catalog */}
        <div className="flex items-center justify-between gap-3 px-1">
          <span className="text-xs text-slate-500">{filteredLanes.length.toLocaleString()} of {mergedLanes.length.toLocaleString()} lanes</span>
          {groupedLanes.length > 0 ? (
            <div className="flex gap-2">
              <button type="button" onClick={() => setAllVisibleGroupsCollapsed(false)} className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-semibold text-slate-700 transition hover:bg-slate-50">Expand all</button>
              <button type="button" onClick={() => setAllVisibleGroupsCollapsed(true)} className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-semibold text-slate-700 transition hover:bg-slate-50">Collapse all</button>
            </div>
          ) : null}
        </div>

        {groupedLanes.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-500">
            No lanes matched the current search and filter combination.
            {hasActiveFilters ? (
              <div className="mt-4">
                <button type="button" onClick={clearAllFilters} className="rounded-full border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50">Clear filters</button>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="space-y-3">
            {groupedLanes.map((group) => (
              <section key={group.key} className="space-y-3">
                {(() => {
                  const attentionCount = countAttentionItems(group.items);
                  const collapsed = collapsedGroups[group.key];
                  return (
                    <>
                      <button
                        type="button"
                        aria-expanded={!collapsed}
                        aria-controls={`security-group-${group.key}`}
                        onClick={() => toggleGroupCollapsed(group.key)}
                        className="flex w-full flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-left shadow-sm transition hover:border-slate-300"
                      >
                        <div className="flex items-center gap-3">
                          <h3 className="text-sm font-semibold text-slate-900">{group.label}</h3>
                          <span className="text-xs text-slate-400">{group.items.length} lane{group.items.length === 1 ? "" : "s"}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${attentionCount > 0 ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"}`}>
                            {attentionCount > 0 ? `${attentionCount} need${attentionCount === 1 ? "s" : ""} attention` : "All clear"}
                          </span>
                          <span className="text-xs text-slate-400">{collapsed ? "▶" : "▼"}</span>
                        </div>
                      </button>
                      {collapsed ? null : (
                        <div id={`security-group-${group.key}`} className="grid gap-4 xl:grid-cols-2">
                          {group.items.map(({ item, summary }) => (
                            <LaneCard key={item.key} item={item} summary={summary} />
                          ))}
                        </div>
                      )}
                    </>
                  );
                })()}
              </section>
            ))}
          </div>
        )}
      </section>

      {/* Support tools */}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-base font-semibold text-slate-900">Support Tools</h2>
        <div className="mt-4 grid gap-4 xl:grid-cols-2">
          {SUPPORT_TOOLS.map((card) => (
            <SupportCard key={card.title} card={card} />
          ))}
        </div>
      </section>
    </div>
  );
}

