import { useDeferredValue, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import { AzureSecurityLaneHero, AzureSecurityMetricCard, LaneSummaryPanel } from "../components/AzureSecurityLane.tsx";
import SecurityReviewPagination, { sliceSecurityReviewPage, useSecurityReviewPagination } from "../components/SecurityReviewPagination.tsx";
import { api, type AzureDirectoryObject } from "../lib/api.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";

type IdentityFocus = "all" | "apps-needing-review" | "enterprise-apps" | "groups" | "roles";

const EMPTY_DIRECTORY_OBJECTS: AzureDirectoryObject[] = [];

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "No refresh recorded";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function parseNumber(value: string | null | undefined): number {
  const parsed = Number(value || "0");
  return Number.isFinite(parsed) ? parsed : 0;
}

function matchesSearch(parts: Array<string | string[]>, search: string): boolean {
  if (!search) return true;
  const normalizedSearch = search.toLowerCase();
  return parts
    .flatMap((part) => (Array.isArray(part) ? part : [part]))
    .some((part) => String(part || "").toLowerCase().includes(normalizedSearch));
}

function daysUntil(value: string): number | null {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  if (Number.isNaN(parsed)) return null;
  return Math.floor((parsed - Date.now()) / 86_400_000);
}

function isExternalAudience(app: AzureDirectoryObject): boolean {
  const audience = String(app.extra.sign_in_audience || "");
  return Boolean(audience && audience !== "AzureADMyOrg");
}

function hasOwnerGap(app: AzureDirectoryObject): boolean {
  return parseNumber(app.extra.owner_count) === 0 || Boolean(app.extra.owner_lookup_error);
}

function appFlags(app: AzureDirectoryObject): string[] {
  const flags: string[] = [];
  if (hasOwnerGap(app)) {
    flags.push(app.extra.owner_lookup_error ? "Owner lookup needs attention" : "No application owners recorded");
  }
  if (isExternalAudience(app)) {
    flags.push("Allows sign-ins outside the home tenant");
  }
  const expiryDays = daysUntil(app.extra.next_credential_expiry || "");
  if (expiryDays !== null && expiryDays <= 30) {
    flags.push(expiryDays < 0 ? "Credential has already expired" : "Credential expires within 30 days");
  }
  return flags;
}

function buildIdentityRoute(tab: string, objectId: string): string {
  return `/identity?tab=${encodeURIComponent(tab)}&objectId=${encodeURIComponent(objectId)}`;
}

function groupTags(group: AzureDirectoryObject): string[] {
  const tags: string[] = [];
  if (group.enabled) tags.push("Security-enabled");
  if ((group.extra.group_types || "").includes("Unified")) tags.push("Collaboration group");
  if (group.mail) tags.push("Mail-enabled");
  if (tags.length === 0) tags.push("Directory group");
  return tags;
}

function SectionFrame({
  title,
  description,
  count,
  children,
}: {
  title: string;
  description: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
          <div className="mt-1 text-sm text-slate-500">{description}</div>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
          {count.toLocaleString()}
        </span>
      </div>
      <div className="mt-5">{children}</div>
    </section>
  );
}

export default function AzureSecurityIdentityReviewPage() {
  const [search, setSearch] = useState("");
  const [focus, setFocus] = useState<IdentityFocus>("all");
  const deferredSearch = useDeferredValue(search);

  const groupsQuery = useQuery({
    queryKey: ["azure", "groups", { search: "" }],
    queryFn: () => api.getAzureGroups(""),
    ...getPollingQueryOptions("slow_5m"),
  });
  const enterpriseAppsQuery = useQuery({
    queryKey: ["azure", "enterprise-apps", { search: "" }],
    queryFn: () => api.getAzureEnterpriseApps(""),
    ...getPollingQueryOptions("slow_5m"),
  });
  const appRegistrationsQuery = useQuery({
    queryKey: ["azure", "app-registrations", { search: "" }],
    queryFn: () => api.getAzureAppRegistrations(""),
    ...getPollingQueryOptions("slow_5m"),
  });
  const rolesQuery = useQuery({
    queryKey: ["azure", "directory-roles", { search: "" }],
    queryFn: () => api.getAzureDirectoryRoles(""),
    ...getPollingQueryOptions("slow_5m"),
  });
  const statusQuery = useQuery({
    queryKey: ["azure", "status"],
    queryFn: () => api.getAzureStatus(),
    ...getPollingQueryOptions("slow_5m"),
  });

  const loading = [
    groupsQuery,
    enterpriseAppsQuery,
    appRegistrationsQuery,
    rolesQuery,
  ].some((query) => query.isLoading);
  const failure = [groupsQuery, enterpriseAppsQuery, appRegistrationsQuery, rolesQuery].find((query) => query.isError);

  const groups = groupsQuery.data ?? EMPTY_DIRECTORY_OBJECTS;
  const enterpriseApps = enterpriseAppsQuery.data ?? EMPTY_DIRECTORY_OBJECTS;
  const appRegistrations = appRegistrationsQuery.data ?? EMPTY_DIRECTORY_OBJECTS;
  const roles = rolesQuery.data ?? EMPTY_DIRECTORY_OBJECTS;

  const collaborationGroups = useMemo(
    () => groups.filter((group) => (group.extra.group_types || "").includes("Unified") || Boolean(group.mail)),
    [groups],
  );
  const securityGroups = useMemo(() => groups.filter((group) => group.enabled === true), [groups]);
  const flaggedApps = useMemo(() => appRegistrations.filter((app) => appFlags(app).length > 0), [appRegistrations]);
  const ownerGapCount = useMemo(() => appRegistrations.filter((app) => hasOwnerGap(app)).length, [appRegistrations]);
  const externalAudienceCount = useMemo(
    () => appRegistrations.filter((app) => isExternalAudience(app)).length,
    [appRegistrations],
  );

  const filteredFlaggedApps = useMemo(() => {
    const rows = focus === "all" || focus === "apps-needing-review" ? flaggedApps : [];
    return rows.filter((app) =>
      matchesSearch(
        [
          app.display_name,
          app.app_id,
          app.extra.sign_in_audience,
          app.extra.owner_names,
          app.extra.owner_lookup_error,
          appFlags(app),
        ],
        deferredSearch,
      ),
    );
  }, [deferredSearch, flaggedApps, focus]);

  const filteredEnterpriseApps = useMemo(() => {
    const rows = focus === "all" || focus === "enterprise-apps" ? enterpriseApps : [];
    return rows.filter((app) =>
      matchesSearch(
        [app.display_name, app.app_id, app.extra.service_principal_type, app.enabled === false ? "disabled" : "enabled"],
        deferredSearch,
      ),
    );
  }, [deferredSearch, enterpriseApps, focus]);

  const filteredGroups = useMemo(() => {
    const rows = focus === "all" || focus === "groups" ? groups : [];
    return rows.filter((group) =>
      matchesSearch([group.display_name, group.mail, group.extra.group_types, groupTags(group)], deferredSearch),
    );
  }, [deferredSearch, focus, groups]);

  const filteredRoles = useMemo(() => {
    const rows = focus === "all" || focus === "roles" ? roles : [];
    return rows.filter((role) => matchesSearch([role.display_name, role.extra.description], deferredSearch));
  }, [deferredSearch, focus, roles]);

  const ownerLookupWarnings = useMemo(
    () =>
      appRegistrations
        .filter((app) => app.extra.owner_lookup_error)
        .map((app) => `${app.display_name || app.app_id}: ${app.extra.owner_lookup_error}`),
    [appRegistrations],
  );
  const flaggedAppsPagination = useSecurityReviewPagination(
    `${deferredSearch}|${focus}|flagged|${filteredFlaggedApps.length}`,
    filteredFlaggedApps.length,
  );
  const enterpriseAppsPagination = useSecurityReviewPagination(
    `${deferredSearch}|${focus}|enterprise|${filteredEnterpriseApps.length}`,
    filteredEnterpriseApps.length,
  );
  const rolesPagination = useSecurityReviewPagination(
    `${deferredSearch}|${focus}|roles|${filteredRoles.length}`,
    filteredRoles.length,
  );
  const groupsPagination = useSecurityReviewPagination(
    `${deferredSearch}|${focus}|groups|${filteredGroups.length}`,
    filteredGroups.length,
  );
  const visibleFlaggedApps = useMemo(
    () => sliceSecurityReviewPage(filteredFlaggedApps, flaggedAppsPagination.pageStart, flaggedAppsPagination.pageSize),
    [filteredFlaggedApps, flaggedAppsPagination.pageSize, flaggedAppsPagination.pageStart],
  );
  const visibleEnterpriseApps = useMemo(
    () => sliceSecurityReviewPage(filteredEnterpriseApps, enterpriseAppsPagination.pageStart, enterpriseAppsPagination.pageSize),
    [enterpriseAppsPagination.pageSize, enterpriseAppsPagination.pageStart, filteredEnterpriseApps],
  );
  const visibleRoles = useMemo(
    () => sliceSecurityReviewPage(filteredRoles, rolesPagination.pageStart, rolesPagination.pageSize),
    [filteredRoles, rolesPagination.pageSize, rolesPagination.pageStart],
  );
  const visibleGroups = useMemo(
    () => sliceSecurityReviewPage(filteredGroups, groupsPagination.pageStart, groupsPagination.pageSize),
    [filteredGroups, groupsPagination.pageSize, groupsPagination.pageStart],
  );

  if (loading) {
    return <AzurePageSkeleton titleWidth="w-60" subtitleWidth="w-[42rem]" statCount={6} sectionCount={4} />;
  }

  if (failure) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load identity review: {failure.error instanceof Error ? failure.error.message : "Unknown error"}
      </div>
    );
  }

  const directoryDataset = statusQuery.data?.datasets?.find((dataset) => dataset.key === "directory");

  return (
    <div className="space-y-6">
      <AzureSecurityLaneHero
        title="Identity Review"
        description="Review groups, enterprise applications, app registrations, and directory roles from one security-first lane. Use this page for posture review, then pivot into the hidden raw inventory only when you need source-record detail."
        accent="violet"
        refreshLabel="Directory refresh"
        refreshValue={formatTimestamp(directoryDataset?.last_refresh ?? statusQuery.data?.last_refresh)}
        actions={[
          { label: "Back to Security workspace", to: "/security", tone: "secondary" },
          { label: "Open Application Hygiene", to: "/security/app-hygiene" },
          { label: "Open raw identity inventory", to: "/identity", tone: "secondary" },
        ]}
      />

      <LaneSummaryPanel laneKey="identity-review" />

      <section className="grid gap-4 xl:grid-cols-3 md:grid-cols-2">
        <AzureSecurityMetricCard
          label="Enterprise apps"
          value={enterpriseApps.length}
          detail="Enterprise applications cached from Microsoft Entra service principals."
          tone="sky"
        />
        <AzureSecurityMetricCard
          label="App registrations"
          value={appRegistrations.length}
          detail="Application identities that can be reviewed in more detail from Application Hygiene."
          tone="amber"
        />
        <AzureSecurityMetricCard
          label="Directory roles"
          value={roles.length}
          detail="Available directory roles cached for identity review and drill-in."
          tone="rose"
        />
        <AzureSecurityMetricCard
          label="Security groups"
          value={securityGroups.length}
          detail="Security-enabled groups that shape access decisions across the tenant."
          tone="emerald"
        />
        <AzureSecurityMetricCard
          label="Collaboration groups"
          value={collaborationGroups.length}
          detail="Unified or mail-enabled groups worth reviewing for external or broad collaboration scope."
          tone="violet"
        />
        <AzureSecurityMetricCard
          label="Apps needing review"
          value={`${flaggedApps.length.toLocaleString()} (${ownerGapCount.toLocaleString()} owner gaps / ${externalAudienceCount.toLocaleString()} external)`}
          detail="Owner coverage and external audience signals derived from the cached application inventory."
          tone="amber"
        />
      </section>

      {ownerLookupWarnings.length > 0 ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-amber-900">Owner lookup warnings</h2>
          <div className="mt-3 space-y-2">
            {ownerLookupWarnings.map((warning) => (
              <div key={warning} className="rounded-xl bg-white/70 px-4 py-3 text-sm text-amber-900">
                {warning}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Scope and filters</h2>
            <div className="mt-1 text-sm text-slate-500">
              Search across identity surfaces or narrow the lane to the directory area you want to review first.
            </div>
          </div>
          <div className="text-sm text-slate-500">
            {filteredFlaggedApps.length + filteredEnterpriseApps.length + filteredGroups.length + filteredRoles.length} visible identity records
          </div>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px]">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search apps, roles, groups, owners, or review flags..."
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
          />
          <select
            value={focus}
            onChange={(event) => setFocus(event.target.value as IdentityFocus)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
          >
            <option value="all">All identity surfaces</option>
            <option value="apps-needing-review">Applications needing review</option>
            <option value="enterprise-apps">Enterprise apps</option>
            <option value="groups">Groups</option>
            <option value="roles">Directory roles</option>
          </select>
        </div>
      </section>

      <SectionFrame
        title="Applications needing review"
        description="App registrations with external audience, owner coverage gaps, or near-term credential attention."
        count={filteredFlaggedApps.length}
      >
        {filteredFlaggedApps.length === 0 ? (
          <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">No application registrations match the current review filters.</div>
        ) : (
          <div className="space-y-4">
            <SecurityReviewPagination
              count={filteredFlaggedApps.length}
              currentPage={flaggedAppsPagination.currentPage}
              pageSize={flaggedAppsPagination.pageSize}
              setCurrentPage={flaggedAppsPagination.setCurrentPage}
              setPageSize={flaggedAppsPagination.setPageSize}
              totalPages={flaggedAppsPagination.totalPages}
              noun="flagged application registration(s)"
            />
            <div className="grid gap-4 xl:grid-cols-2">
              {visibleFlaggedApps.map((app) => (
              <section key={app.id} className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-lg font-semibold text-slate-900">{app.display_name}</h3>
                    <div className="mt-1 text-sm text-slate-500">{app.app_id || app.id}</div>
                  </div>
                  <Link
                    to={buildIdentityRoute("app-registrations", app.id)}
                    className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                  >
                    Open raw inventory
                  </Link>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                    {app.extra.sign_in_audience || "Audience unknown"}
                  </span>
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                    {parseNumber(app.extra.owner_count).toLocaleString()} owner(s)
                  </span>
                  {app.extra.next_credential_expiry ? (
                    <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700">
                      Next expiry: {formatTimestamp(app.extra.next_credential_expiry)}
                    </span>
                  ) : null}
                </div>
                <div className="mt-4 space-y-2">
                  {appFlags(app).map((flag) => (
                    <div key={`${app.id}-${flag}`} className="rounded-xl bg-white px-4 py-3 text-sm text-slate-700">
                      {flag}
                    </div>
                  ))}
                </div>
              </section>
              ))}
            </div>
          </div>
        )}
      </SectionFrame>

      <SectionFrame
        title="Enterprise applications"
        description="Cached service principals for application access review and directory drill-in."
        count={filteredEnterpriseApps.length}
      >
        {filteredEnterpriseApps.length === 0 ? (
          <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">No enterprise applications match the current filters.</div>
        ) : (
          <div className="space-y-4">
            <SecurityReviewPagination
              count={filteredEnterpriseApps.length}
              currentPage={enterpriseAppsPagination.currentPage}
              pageSize={enterpriseAppsPagination.pageSize}
              setCurrentPage={enterpriseAppsPagination.setCurrentPage}
              setPageSize={enterpriseAppsPagination.setPageSize}
              totalPages={enterpriseAppsPagination.totalPages}
              noun="enterprise application(s)"
            />
            <div className="grid gap-4 xl:grid-cols-2">
              {visibleEnterpriseApps.map((app) => (
              <section key={app.id} className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-lg font-semibold text-slate-900">{app.display_name}</h3>
                    <div className="mt-1 text-sm text-slate-500">{app.app_id || app.id}</div>
                  </div>
                  <Link
                    to={buildIdentityRoute("enterprise-apps", app.id)}
                    className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                  >
                    Open raw inventory
                  </Link>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">
                    {app.extra.service_principal_type || "Service principal"}
                  </span>
                  <span className={`rounded-full px-3 py-1 text-xs font-medium ${app.enabled === false ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"}`}>
                    {app.enabled === false ? "Disabled" : "Enabled"}
                  </span>
                </div>
              </section>
              ))}
            </div>
          </div>
        )}
      </SectionFrame>

      <div className="grid gap-6 xl:grid-cols-2">
        <SectionFrame
          title="Directory roles"
          description="Role definitions cached from Microsoft Entra for identity drill-in and access review context."
          count={filteredRoles.length}
        >
          {filteredRoles.length === 0 ? (
            <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">No directory roles match the current filters.</div>
          ) : (
            <div className="space-y-4">
              <SecurityReviewPagination
                count={filteredRoles.length}
                currentPage={rolesPagination.currentPage}
                pageSize={rolesPagination.pageSize}
                setCurrentPage={rolesPagination.setCurrentPage}
                setPageSize={rolesPagination.setPageSize}
                totalPages={rolesPagination.totalPages}
                noun="directory role record(s)"
              />
              <div className="space-y-3">
                {visibleRoles.map((role) => (
                <section key={role.id} className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="font-semibold text-slate-900">{role.display_name}</h3>
                      <div className="mt-1 text-sm text-slate-500">{role.extra.description || "No role description cached."}</div>
                    </div>
                    <Link
                      to={buildIdentityRoute("roles", role.id)}
                      className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                    >
                      Open raw inventory
                    </Link>
                  </div>
                </section>
                ))}
              </div>
            </div>
          )}
        </SectionFrame>

        <SectionFrame
          title="Group surfaces"
          description="Security-enabled and collaboration groups that shape access and sharing posture."
          count={filteredGroups.length}
        >
          {filteredGroups.length === 0 ? (
            <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">No groups match the current filters.</div>
          ) : (
            <div className="space-y-4">
              <SecurityReviewPagination
                count={filteredGroups.length}
                currentPage={groupsPagination.currentPage}
                pageSize={groupsPagination.pageSize}
                setCurrentPage={groupsPagination.setCurrentPage}
                setPageSize={groupsPagination.setPageSize}
                totalPages={groupsPagination.totalPages}
                noun="group record(s)"
              />
              <div className="space-y-3">
                {visibleGroups.map((group) => (
                <section key={group.id} className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="font-semibold text-slate-900">{group.display_name}</h3>
                      <div className="mt-1 text-sm text-slate-500">{group.mail || group.id}</div>
                    </div>
                    <Link
                      to={buildIdentityRoute("groups", group.id)}
                      className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                    >
                      Open raw inventory
                    </Link>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {groupTags(group).map((tag) => (
                      <span key={`${group.id}-${tag}`} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                        {tag}
                      </span>
                    ))}
                  </div>
                </section>
                ))}
              </div>
            </div>
          )}
        </SectionFrame>
      </div>
    </div>
  );
}
