import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import AzureSourceBadge from "../components/AzureSourceBadge.tsx";
import { api } from "../lib/api.ts";

type ToolAction = {
  label: string;
  to: string;
  external?: boolean;
  tone?: "primary" | "secondary";
};

type ToolCardDefinition = {
  eyebrow: string;
  title: string;
  description: string;
  status: "Ready now" | "In build" | "Planned";
  actions: ToolAction[];
};

type BuildQueueItem = {
  title: string;
  description: string;
};

const controlPlaneCards: ToolCardDefinition[] = [
  {
    eyebrow: "Control Plane",
    title: "Identity and Access",
    description:
      "Start tenant security work from the identity inventory, sign-in health, and the Entra admin surface for roles, app access, and directory posture.",
    status: "Ready now",
    actions: [
      { label: "Identity Inventory", to: "/identity" },
      { label: "Account Health", to: "/account-health", tone: "secondary" },
      { label: "Entra Admin Center", to: "https://entra.microsoft.com/", external: true, tone: "secondary" },
    ],
  },
  {
    eyebrow: "Control Plane",
    title: "Detection and Response",
    description:
      "Work alerts, correlate Azure signals, and keep one landing zone for triage before the dedicated incident tooling arrives here.",
    status: "Ready now",
    actions: [
      { label: "Azure Alerts", to: "/alerts" },
      { label: "Microsoft Defender", to: "https://security.microsoft.com/", external: true, tone: "secondary" },
      { label: "Azure Portal", to: "https://portal.azure.com/", external: true, tone: "secondary" },
    ],
  },
  {
    eyebrow: "Control Plane",
    title: "User and Access Operations",
    description:
      "Pivot into user lifecycle checks, directory hygiene, and shared operator tools when an identity issue becomes an access or operational task.",
    status: "Ready now",
    actions: [
      { label: "Azure Users", to: "/users" },
      { label: "Shared Admin Tools", to: "/tools", tone: "secondary" },
    ],
  },
  {
    eyebrow: "Control Plane",
    title: "Application and Resource Audit",
    description:
      "Review enterprise apps, app registrations, subscriptions, and exposed resources from one place while we wire in deeper security-specific checks.",
    status: "In build",
    actions: [
      { label: "Resource Inventory", to: "/resources" },
      { label: "Azure Overview", to: "/", tone: "secondary" },
    ],
  },
];

const starterTools: ToolCardDefinition[] = [
  {
    eyebrow: "Starter Tool",
    title: "Security Incident Copilot",
    description:
      "Run guided incident intake, let the copilot ask for missing evidence, query grounded Azure and local sources, auto-start safe mailbox delegate scans when the case needs them, and export a repeatable investigation handoff.",
    status: "Ready now",
    actions: [
      { label: "Open Security Copilot", to: "/security/copilot" },
      { label: "Open Azure Alerts", to: "/alerts", tone: "secondary" },
    ],
  },
  {
    eyebrow: "Starter Tool",
    title: "Identity Review Lane",
    description:
      "Use the current app inventory to review enterprise apps, app registrations, directory roles, and user posture without leaving the Azure surface.",
    status: "Ready now",
    actions: [
      { label: "Open Identity Inventory", to: "/identity" },
      { label: "Review Account Health", to: "/account-health", tone: "secondary" },
    ],
  },
  {
    eyebrow: "Starter Tool",
    title: "Alert Triage Lane",
    description:
      "Work Azure alerts, turn findings into tracked operator follow-up, and hand active investigations to the security copilot when you need grounded cross-source evidence.",
    status: "Ready now",
    actions: [
      { label: "Open Alert Desk", to: "/alerts" },
      { label: "Open Security Copilot", to: "/security/copilot", tone: "secondary" },
    ],
  },
  {
    eyebrow: "Starter Tool",
    title: "Privileged Access Review",
    description:
      "Review elevated Azure RBAC assignments, guest or external privileged principals, stale privileged users, and emergency account watchlists from one dedicated security lane.",
    status: "Ready now",
    actions: [
      { label: "Open Access Review", to: "/security/access-review" },
      { label: "Review Azure Users", to: "/users", tone: "secondary" },
    ],
  },
  {
    eyebrow: "Starter Tool",
    title: "Application Hygiene",
    description:
      "Review app registration owner coverage, expiring client secrets and certificates, external audience exposure, and publisher trust from one security lane.",
    status: "Ready now",
    actions: [
      { label: "Open Application Hygiene", to: "/security/app-hygiene" },
      { label: "Review App Inventory", to: "/identity", tone: "secondary" },
    ],
  },
];

const buildQueue: BuildQueueItem[] = [
  {
    title: "Conditional access change tracker",
    description: "Track policy drift and highlight high-impact changes before they become user-impacting outages.",
  },
  {
    title: "Break-glass account validation",
    description: "Verify emergency accounts, MFA posture, and sign-in health on a repeatable schedule.",
  },
  {
    title: "Directory role membership review",
    description: "Add direct Entra directory-role membership coverage beside the shipped Azure RBAC privileged access review lane.",
  },
  {
    title: "Enterprise app permission review",
    description: "Layer delegated consent, app permissions, and service principal grant review on top of the shipped application hygiene lane.",
  },
  {
    title: "Guest and external access review",
    description: "Build a focused review lane for external users, shared collaboration risk, and dormant access.",
  },
];

function MetricCard({ label, value, accent = "text-sky-700" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${accent}`}>{value}</div>
    </div>
  );
}

function ToolActionButton({ action }: { action: ToolAction }) {
  const className = [
    "inline-flex items-center rounded-lg px-3 py-2 text-sm font-medium transition",
    action.tone === "secondary"
      ? "border border-slate-300 text-slate-700 hover:bg-slate-50"
      : "bg-sky-700 text-white hover:bg-sky-800",
  ].join(" ");

  if (action.external) {
    return (
      <a href={action.to} target="_blank" rel="noreferrer" className={className}>
        {action.label}
      </a>
    );
  }

  return (
    <Link to={action.to} className={className}>
      {action.label}
    </Link>
  );
}

function StatusPill({ status }: { status: ToolCardDefinition["status"] }) {
  const className =
    status === "Ready now"
      ? "bg-emerald-50 text-emerald-700"
      : status === "In build"
        ? "bg-amber-50 text-amber-700"
        : "bg-slate-100 text-slate-600";

  return <span className={`rounded-full px-3 py-1 text-xs font-semibold ${className}`}>{status}</span>;
}

function ToolCard({ eyebrow, title, description, status, actions }: ToolCardDefinition) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{eyebrow}</div>
        <StatusPill status={status} />
      </div>
      <h3 className="mt-3 text-lg font-semibold text-slate-900">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {actions.map((action) => (
          <ToolActionButton key={`${title}-${action.label}`} action={action} />
        ))}
      </div>
    </section>
  );
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "No refresh recorded yet";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export default function AzureSecurityPage() {
  const overviewQuery = useQuery({
    queryKey: ["azure", "overview", "security-page"],
    queryFn: () => api.getAzureOverview(),
    refetchInterval: 60_000,
  });
  const statusQuery = useQuery({
    queryKey: ["azure", "status", "security-page"],
    queryFn: () => api.getAzureStatus(),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

  if (overviewQuery.isLoading) {
    return <AzurePageSkeleton titleWidth="w-48" subtitleWidth="w-[38rem]" statCount={4} sectionCount={3} />;
  }

  if (overviewQuery.isError || !overviewQuery.data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load Azure security workspace: {overviewQuery.error instanceof Error ? overviewQuery.error.message : "Unknown error"}
      </div>
    );
  }

  const overview = overviewQuery.data;
  const status = statusQuery.data;
  const datasets = status?.datasets ?? overview.datasets;
  const configuredDatasetCount = datasets.filter((dataset) => dataset.configured).length;
  const healthyDatasetCount = datasets.filter((dataset) => dataset.configured && !dataset.error).length;
  const datasetLabel = configuredDatasetCount
    ? `${healthyDatasetCount}/${configuredDatasetCount} configured datasets healthy`
    : "No configured datasets yet";
  const datasetTone = configuredDatasetCount > 0 && healthyDatasetCount === configuredDatasetCount ? "emerald" : "amber";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Azure Security</h1>
        <p className="mt-1 max-w-4xl text-sm text-slate-500">
          Security-focused workspace for Azure identity, alert response, tenant hygiene, and the next wave of operator tools. This first build
          gives the Azure site a dedicated landing zone for security work instead of scattering it across unrelated tabs.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <AzureSourceBadge
            label="Cached Azure identity and inventory context"
            description="This workspace uses the same Azure snapshots that power the identity, account health, and inventory lanes."
          />
          <AzureSourceBadge
            label={status?.refreshing ? "Azure refresh in progress" : "Azure cache ready"}
            description={`Latest Azure refresh: ${formatTimestamp(status?.last_refresh ?? overview.last_refresh)}`}
            tone={status?.refreshing ? "amber" : "emerald"}
          />
          <AzureSourceBadge
            label={datasetLabel}
            description="Configured dataset health for the Azure security workspace."
            tone={datasetTone}
          />
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Users" value={overview.users.toLocaleString()} />
        <MetricCard label="Enterprise Apps" value={overview.enterprise_apps.toLocaleString()} accent="text-indigo-700" />
        <MetricCard label="App Registrations" value={overview.app_registrations.toLocaleString()} accent="text-violet-700" />
        <MetricCard label="Role Assignments" value={overview.role_assignments.toLocaleString()} accent="text-emerald-700" />
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Security Control Planes</h2>
            <p className="mt-1 max-w-3xl text-sm text-slate-500">
              These are the main jump points for Azure security work today while the dedicated workflows on this page keep expanding.
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            <div className="font-semibold text-slate-900">Last tenant refresh</div>
            <div className="mt-1">{formatTimestamp(status?.last_refresh ?? overview.last_refresh)}</div>
          </div>
        </div>
        <div className="mt-5 grid gap-4 xl:grid-cols-2">
          {controlPlaneCards.map((card) => (
            <ToolCard key={card.title} {...card} />
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Starter Security Tools</h2>
            <p className="mt-1 max-w-3xl text-sm text-slate-500">
              First-pass tool lanes that pull the existing Azure pages into a more intentional security workspace while we build dedicated checks.
            </p>
          </div>
          <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700">Security workspace v1</span>
        </div>
        <div className="mt-5 grid gap-4 xl:grid-cols-2">
          {starterTools.map((card) => (
            <ToolCard key={card.title} {...card} />
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Build Queue</h2>
            <p className="mt-1 max-w-3xl text-sm text-slate-500">
              The next security workflows to turn into first-class tools on this page.
            </p>
          </div>
          <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">Next up</span>
        </div>
        <div className="mt-5 grid gap-3 lg:grid-cols-2">
          {buildQueue.map((item) => (
            <div key={item.title} className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
              <div className="text-sm font-semibold text-slate-900">{item.title}</div>
              <div className="mt-2 text-sm leading-6 text-slate-600">{item.description}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
