import { useDeferredValue, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import { AzureSecurityLaneHero, AzureSecurityMetricCard, azureSecurityToneClasses } from "../components/AzureSecurityLane.tsx";
import SecurityReviewPagination, { sliceSecurityReviewPage, useSecurityReviewPagination } from "../components/SecurityReviewPagination.tsx";
import { api, type AzureDirectoryObject } from "../lib/api.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";
import { daysSince, formatDate, lastSuccessfulText, hasNoSuccessfulSignIn, isLicensedUser, licenseCount, missingFieldLabel } from "../lib/azureSecurityUsers.ts";

type GuestFocus = "priority" | "all-guests" | "old-guests" | "stale-guests" | "disabled-guests";

const EMPTY_DIRECTORY_OBJECTS: AzureDirectoryObject[] = [];

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "No refresh recorded";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function matchesSearch(parts: Array<string | string[]>, search: string): boolean {
  if (!search) return true;
  const normalizedSearch = search.toLowerCase();
  return parts
    .flatMap((part) => (Array.isArray(part) ? part : [part]))
    .some((part) => String(part || "").toLowerCase().includes(normalizedSearch));
}

function isGuestUser(user: AzureDirectoryObject): boolean {
  return user.object_type === "user" && (user.extra.user_type === "Guest" || user.extra.account_class === "guest_external");
}

function guestAgeDays(user: AzureDirectoryObject): number {
  return daysSince(user.extra.created_datetime || "");
}

function isOldGuest(user: AzureDirectoryObject, thresholdDays: number): boolean {
  return guestAgeDays(user) >= thresholdDays;
}

function hasStaleGuestSignIn(user: AzureDirectoryObject, thresholdDays: number): boolean {
  return hasNoSuccessfulSignIn(user, thresholdDays);
}

function isCollaborationSurface(group: AzureDirectoryObject): boolean {
  const groupTypes = String(group.extra.group_types || "");
  return group.object_type === "group" && (groupTypes.includes("Unified") || Boolean(group.mail));
}

function collaborationTags(group: AzureDirectoryObject): string[] {
  const tags: string[] = [];
  if (String(group.extra.group_types || "").includes("Unified")) tags.push("Microsoft 365 group");
  if (group.mail) tags.push("Mail-enabled");
  if (group.enabled) tags.push("Security-enabled");
  if (tags.length === 0) tags.push("Directory group");
  return tags;
}

function isExternalAudienceApp(app: AzureDirectoryObject): boolean {
  const audience = String(app.extra.sign_in_audience || "");
  return app.object_type === "app_registration" && Boolean(audience && audience !== "AzureADMyOrg");
}

function externalAudienceLabel(app: AzureDirectoryObject): string {
  const audience = String(app.extra.sign_in_audience || "");
  if (audience === "AzureADandPersonalMicrosoftAccount") return "Work or school and personal Microsoft accounts";
  if (audience === "AzureADMultipleOrgs") return "Multiple work or school tenants";
  if (audience === "PersonalMicrosoftAccount") return "Personal Microsoft accounts";
  return audience || "External audience";
}

function buildUserRoute(userId: string): string {
  return `/users?userId=${encodeURIComponent(userId)}`;
}

function buildIdentityRoute(tab: string, objectId: string): string {
  return `/identity?tab=${encodeURIComponent(tab)}&objectId=${encodeURIComponent(objectId)}`;
}

function guestFlags(user: AzureDirectoryObject, guestAgeThreshold: number, signInThreshold: number): string[] {
  const flags: string[] = [];
  const ageDays = guestAgeDays(user);
  if (ageDays >= guestAgeThreshold) {
    flags.push(`Guest account is ${ageDays} days old`);
  }
  if (hasStaleGuestSignIn(user, signInThreshold)) {
    flags.push(
      user.extra.last_successful_utc
        ? `No successful sign-in in ${signInThreshold}+ days`
        : "No successful sign-in recorded",
    );
  }
  if (user.enabled === false) flags.push("Disabled guest account still present");
  if (isLicensedUser(user)) flags.push(`${licenseCount(user)} active license${licenseCount(user) === 1 ? "" : "s"}`);
  if (missingFieldLabel(user)) flags.push(`Missing ${missingFieldLabel(user)}`);
  return flags;
}

function guestPriorityScore(user: AzureDirectoryObject, guestAgeThreshold: number, signInThreshold: number): number {
  let score = Number(user.extra.priority_score || 0);
  if (isOldGuest(user, guestAgeThreshold)) score += 20;
  if (hasStaleGuestSignIn(user, signInThreshold)) score += 20;
  if (user.enabled === false) score += 10;
  if (isLicensedUser(user)) score += 10;
  return score;
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

function GuestCard({
  user,
  guestAgeThreshold,
  signInThreshold,
}: {
  user: AzureDirectoryObject;
  guestAgeThreshold: number;
  signInThreshold: number;
}) {
  const flags = guestFlags(user, guestAgeThreshold, signInThreshold);

  return (
    <section className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-slate-900">{user.display_name}</h3>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${azureSecurityToneClasses(user.enabled === false ? "slate" : "rose")}`}>
              {user.enabled === false ? "Disabled guest" : "Guest account"}
            </span>
          </div>
          <div className="mt-1 text-sm text-slate-500">{user.principal_name || user.mail || user.id}</div>
        </div>
        <Link
          to={buildUserRoute(user.id)}
          className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
        >
          Open source record
        </Link>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <div className="rounded-xl bg-white px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Guest age</div>
          <div className="mt-1 text-lg font-semibold text-slate-900">{guestAgeDays(user).toLocaleString()} days</div>
        </div>
        <div className="rounded-xl bg-white px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Last successful sign-in</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{lastSuccessfulText(user)}</div>
        </div>
        <div className="rounded-xl bg-white px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Created</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{formatDate(user.extra.created_datetime)}</div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {flags.map((flag) => (
          <span key={`${user.id}-${flag}`} className="rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-800">
            {flag}
          </span>
        ))}
      </div>
    </section>
  );
}

export default function AzureSecurityGuestAccessReviewPage() {
  const [search, setSearch] = useState("");
  const [focus, setFocus] = useState<GuestFocus>("priority");
  const [guestAgeThreshold, setGuestAgeThreshold] = useState(180);
  const [signInThreshold, setSignInThreshold] = useState(90);
  const deferredSearch = useDeferredValue(search);

  const usersQuery = useQuery({
    queryKey: ["azure", "users", { search: "" }],
    queryFn: () => api.getAzureUsers(""),
    ...getPollingQueryOptions("slow_5m"),
  });
  const groupsQuery = useQuery({
    queryKey: ["azure", "groups", { search: "" }],
    queryFn: () => api.getAzureGroups(""),
    ...getPollingQueryOptions("slow_5m"),
  });
  const appRegistrationsQuery = useQuery({
    queryKey: ["azure", "app-registrations", { search: "" }],
    queryFn: () => api.getAzureAppRegistrations(""),
    ...getPollingQueryOptions("slow_5m"),
  });
  const statusQuery = useQuery({
    queryKey: ["azure", "status"],
    queryFn: () => api.getAzureStatus(),
    ...getPollingQueryOptions("slow_5m"),
  });

  const loading = [usersQuery, groupsQuery, appRegistrationsQuery].some((query) => query.isLoading);
  const failure = [usersQuery, groupsQuery, appRegistrationsQuery].find((query) => query.isError);

  const users = usersQuery.data ?? EMPTY_DIRECTORY_OBJECTS;
  const groups = groupsQuery.data ?? EMPTY_DIRECTORY_OBJECTS;
  const appRegistrations = appRegistrationsQuery.data ?? EMPTY_DIRECTORY_OBJECTS;

  const guestUsers = useMemo(() => users.filter((user) => isGuestUser(user)), [users]);
  const collaborationGroups = useMemo(() => groups.filter((group) => isCollaborationSurface(group)), [groups]);
  const externalAudienceApps = useMemo(
    () => appRegistrations.filter((app) => isExternalAudienceApp(app)),
    [appRegistrations],
  );

  const oldGuestCount = useMemo(
    () => guestUsers.filter((user) => isOldGuest(user, guestAgeThreshold)).length,
    [guestAgeThreshold, guestUsers],
  );
  const staleGuestCount = useMemo(
    () => guestUsers.filter((user) => hasStaleGuestSignIn(user, signInThreshold)).length,
    [guestUsers, signInThreshold],
  );
  const disabledGuestCount = useMemo(
    () => guestUsers.filter((user) => user.enabled === false).length,
    [guestUsers],
  );

  const priorityGuests = useMemo(
    () =>
      [...guestUsers]
        .filter(
          (user) =>
            isOldGuest(user, guestAgeThreshold) ||
            hasStaleGuestSignIn(user, signInThreshold) ||
            user.enabled === false ||
            isLicensedUser(user),
        )
        .sort(
          (left, right) =>
            guestPriorityScore(right, guestAgeThreshold, signInThreshold) -
              guestPriorityScore(left, guestAgeThreshold, signInThreshold) ||
            left.display_name.localeCompare(right.display_name),
        )
        .slice(0, 8),
    [guestAgeThreshold, guestUsers, signInThreshold],
  );

  const filteredGuests = useMemo(() => {
    const sorted = [...guestUsers].sort(
      (left, right) =>
        guestPriorityScore(right, guestAgeThreshold, signInThreshold) -
          guestPriorityScore(left, guestAgeThreshold, signInThreshold) ||
        left.display_name.localeCompare(right.display_name),
    );
    return sorted.filter((user) => {
      if (focus === "priority" && !priorityGuests.some((candidate) => candidate.id === user.id)) return false;
      if (focus === "old-guests" && !isOldGuest(user, guestAgeThreshold)) return false;
      if (focus === "stale-guests" && !hasStaleGuestSignIn(user, signInThreshold)) return false;
      if (focus === "disabled-guests" && user.enabled !== false) return false;
      return matchesSearch(
        [
          user.display_name,
          user.principal_name,
          user.mail,
          user.extra.department,
          user.extra.job_title,
          user.extra.priority_reason,
          guestFlags(user, guestAgeThreshold, signInThreshold),
        ],
        deferredSearch,
      );
    });
  }, [deferredSearch, focus, guestAgeThreshold, guestUsers, priorityGuests, signInThreshold]);

  const filteredGroups = useMemo(
    () =>
      collaborationGroups.filter((group) =>
        matchesSearch([group.display_name, group.mail, group.extra.group_types, collaborationTags(group)], deferredSearch),
      ),
    [collaborationGroups, deferredSearch],
  );

  const filteredApps = useMemo(
    () =>
      externalAudienceApps.filter((app) =>
        matchesSearch(
          [app.display_name, app.app_id, app.extra.sign_in_audience, app.extra.owner_names, externalAudienceLabel(app)],
          deferredSearch,
        ),
      ),
    [deferredSearch, externalAudienceApps],
  );
  const guestsPagination = useSecurityReviewPagination(
    `${deferredSearch}|${focus}|${guestAgeThreshold}|${signInThreshold}|guests|${filteredGuests.length}`,
    filteredGuests.length,
  );
  const groupsPagination = useSecurityReviewPagination(
    `${deferredSearch}|${focus}|${guestAgeThreshold}|${signInThreshold}|groups|${filteredGroups.length}`,
    filteredGroups.length,
  );
  const appsPagination = useSecurityReviewPagination(
    `${deferredSearch}|${focus}|${guestAgeThreshold}|${signInThreshold}|apps|${filteredApps.length}`,
    filteredApps.length,
  );
  const visibleGuests = useMemo(
    () => sliceSecurityReviewPage(filteredGuests, guestsPagination.pageStart, guestsPagination.pageSize),
    [filteredGuests, guestsPagination.pageSize, guestsPagination.pageStart],
  );
  const visibleGroups = useMemo(
    () => sliceSecurityReviewPage(filteredGroups, groupsPagination.pageStart, groupsPagination.pageSize),
    [filteredGroups, groupsPagination.pageSize, groupsPagination.pageStart],
  );
  const visibleApps = useMemo(
    () => sliceSecurityReviewPage(filteredApps, appsPagination.pageStart, appsPagination.pageSize),
    [appsPagination.pageSize, appsPagination.pageStart, filteredApps],
  );

  if (loading) {
    return <AzurePageSkeleton titleWidth="w-72" subtitleWidth="w-[46rem]" statCount={6} sectionCount={4} />;
  }

  if (failure) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load guest access review: {failure.error instanceof Error ? failure.error.message : "Unknown error"}
      </div>
    );
  }

  const directoryDataset = statusQuery.data?.datasets?.find((dataset) => dataset.key === "directory");

  return (
    <div className="space-y-6">
      <AzureSecurityLaneHero
        title="Guest Access Review"
        description="Review guest identities, collaboration groups that can widen external reach, and app registrations that accept identities from outside the home tenant. This lane is grounded in cached directory metadata and is designed to prioritize what needs a deeper follow-up in Entra, SharePoint, or the raw inventory views."
        accent="emerald"
        refreshLabel="Directory refresh"
        refreshValue={formatTimestamp(directoryDataset?.last_refresh ?? statusQuery.data?.last_refresh)}
        actions={[
          { label: "Back to Security workspace", to: "/security", tone: "secondary" },
          { label: "Open User Review", to: "/security/user-review" },
          { label: "Open raw user inventory", to: "/users", tone: "secondary" },
        ]}
      />

      <section className="rounded-2xl border border-sky-200 bg-sky-50 p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-sky-900">Coverage note</h2>
        <p className="mt-2 text-sm leading-6 text-sky-900/90">
          This lane highlights guest-age, stale-sign-in, collaboration-surface, and external-app-audience signals from the cached Azure directory
          dataset. It does not enumerate live guest membership for every group or active sharing links in downstream workloads.
        </p>
      </section>

      <section className="grid gap-4 xl:grid-cols-3 md:grid-cols-2">
        <AzureSecurityMetricCard
          label="Guest identities"
          value={guestUsers.length}
          detail="Guest and external users cached from Microsoft Entra."
          tone="emerald"
        />
        <AzureSecurityMetricCard
          label={`Old guests (${guestAgeThreshold}d+)`}
          value={oldGuestCount}
          detail="Guests older than the current review threshold."
          tone="amber"
        />
        <AzureSecurityMetricCard
          label={`Stale sign-ins (${signInThreshold}d+)`}
          value={staleGuestCount}
          detail="Guests with no successful sign-in in the current threshold window."
          tone="rose"
        />
        <AzureSecurityMetricCard
          label="Disabled guests"
          value={disabledGuestCount}
          detail="Disabled guest identities that still remain in the directory."
          tone="slate"
        />
        <AzureSecurityMetricCard
          label="Collaboration surfaces"
          value={collaborationGroups.length}
          detail="Mail-enabled or Microsoft 365 groups that can widen external collaboration scope."
          tone="violet"
        />
        <AzureSecurityMetricCard
          label="External audience apps"
          value={externalAudienceApps.length}
          detail="App registrations that accept identities beyond the home tenant."
          tone="sky"
        />
      </section>

      <SectionFrame
        title="Priority guest queue"
        description="Guest identities ranked for quick triage based on age, stale sign-ins, disabled state, and existing account hygiene signals."
        count={priorityGuests.length}
      >
        {priorityGuests.length === 0 ? (
          <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">
            No guest identities currently meet the review thresholds from the cached directory snapshot.
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {priorityGuests.map((user) => (
              <GuestCard
                key={user.id}
                user={user}
                guestAgeThreshold={guestAgeThreshold}
                signInThreshold={signInThreshold}
              />
            ))}
          </div>
        )}
      </SectionFrame>

      <SectionFrame
        title="Guest identity review"
        description="Search and filter the guest-user cohort, then pivot into the raw user surface when you need direct admin actions or deeper profile detail."
        count={filteredGuests.length}
      >
        <div className="mb-5 grid gap-3 xl:grid-cols-[minmax(0,1fr)_220px_160px_160px]">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search guest users, risk reasons, or flags..."
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
          />
          <select
            value={focus}
            onChange={(event) => setFocus(event.target.value as GuestFocus)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
          >
            <option value="priority">Priority queue</option>
            <option value="all-guests">All guests</option>
            <option value="old-guests">Old guests</option>
            <option value="stale-guests">Stale sign-ins</option>
            <option value="disabled-guests">Disabled guests</option>
          </select>
          <label className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Guest age days</div>
            <input
              type="number"
              min={30}
              step={30}
              value={guestAgeThreshold}
              onChange={(event) => setGuestAgeThreshold(Math.max(30, Number(event.target.value) || 30))}
              className="mt-2 w-full bg-transparent outline-none"
            />
          </label>
          <label className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Sign-in days</div>
            <input
              type="number"
              min={30}
              step={30}
              value={signInThreshold}
              onChange={(event) => setSignInThreshold(Math.max(30, Number(event.target.value) || 30))}
              className="mt-2 w-full bg-transparent outline-none"
            />
          </label>
        </div>

        <div className="mb-5">
          <SecurityReviewPagination
            count={filteredGuests.length}
            currentPage={guestsPagination.currentPage}
            pageSize={guestsPagination.pageSize}
            setCurrentPage={guestsPagination.setCurrentPage}
            setPageSize={guestsPagination.setPageSize}
            totalPages={guestsPagination.totalPages}
            noun="matching guest account(s)"
          />
        </div>

        {filteredGuests.length === 0 ? (
          <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">
            No guest identities matched the current filters.
          </div>
        ) : (
          <div className="space-y-3">
            {visibleGuests.map((user) => (
              <div key={user.id} className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-base font-semibold text-slate-900">{user.display_name}</h3>
                      <span className={`rounded-full px-3 py-1 text-xs font-semibold ${azureSecurityToneClasses(user.enabled === false ? "slate" : "emerald")}`}>
                        {user.enabled === false ? "Disabled" : "Enabled"}
                      </span>
                    </div>
                    <div className="mt-1 text-sm text-slate-500">{user.principal_name || user.mail || user.id}</div>
                  </div>
                  <Link
                    to={buildUserRoute(user.id)}
                    className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                  >
                    Open source record
                  </Link>
                </div>
                <div className="mt-3 text-sm text-slate-600">
                  Guest age: <span className="font-medium text-slate-900">{guestAgeDays(user)} days</span> • Last successful sign-in:{" "}
                  <span className="font-medium text-slate-900">{lastSuccessfulText(user)}</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {guestFlags(user, guestAgeThreshold, signInThreshold).map((flag) => (
                    <span key={`${user.id}-${flag}`} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                      {flag}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionFrame>

      <SectionFrame
        title="Collaboration surfaces"
        description="Groups worth reviewing when guest access might spread through Teams, Outlook, or Microsoft 365 collaboration rather than direct directory assignment."
        count={filteredGroups.length}
      >
        {filteredGroups.length === 0 ? (
          <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">
            No collaboration surfaces matched the current search.
          </div>
        ) : (
          <div className="space-y-4">
            <SecurityReviewPagination
              count={filteredGroups.length}
              currentPage={groupsPagination.currentPage}
              pageSize={groupsPagination.pageSize}
              setCurrentPage={groupsPagination.setCurrentPage}
              setPageSize={groupsPagination.setPageSize}
              totalPages={groupsPagination.totalPages}
              noun="matching collaboration surface(s)"
            />
            <div className="grid gap-4 xl:grid-cols-2">
              {visibleGroups.map((group) => (
              <section key={group.id} className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="text-base font-semibold text-slate-900">{group.display_name}</h3>
                    <div className="mt-1 text-sm text-slate-500">{group.mail || group.id}</div>
                  </div>
                  <Link
                    to={buildIdentityRoute("groups", group.id)}
                    className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                  >
                    Open raw group
                  </Link>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {collaborationTags(group).map((tag) => (
                    <span key={`${group.id}-${tag}`} className="rounded-full bg-violet-50 px-3 py-1 text-xs font-medium text-violet-700">
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

      <SectionFrame
        title="External application surfaces"
        description="App registrations that accept identities from outside the home tenant and deserve a tighter review of owners, permissions, and business need."
        count={filteredApps.length}
      >
        {filteredApps.length === 0 ? (
          <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">
            No external-audience app registrations matched the current search.
          </div>
        ) : (
          <div className="space-y-4">
            <SecurityReviewPagination
              count={filteredApps.length}
              currentPage={appsPagination.currentPage}
              pageSize={appsPagination.pageSize}
              setCurrentPage={appsPagination.setCurrentPage}
              setPageSize={appsPagination.setPageSize}
              totalPages={appsPagination.totalPages}
              noun="matching external application surface(s)"
            />
            <div className="grid gap-4 xl:grid-cols-2">
              {visibleApps.map((app) => (
              <section key={app.id} className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="text-base font-semibold text-slate-900">{app.display_name}</h3>
                    <div className="mt-1 text-sm text-slate-500">{app.app_id || app.id}</div>
                  </div>
                  <Link
                    to={buildIdentityRoute("app-registrations", app.id)}
                    className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                  >
                    Open raw inventory
                  </Link>
                </div>
                <div className="mt-4 rounded-xl bg-white px-4 py-3 text-sm text-slate-700">
                  Audience: <span className="font-medium text-slate-900">{externalAudienceLabel(app)}</span>
                </div>
                <div className="mt-3 text-sm text-slate-600">
                  Owners: <span className="font-medium text-slate-900">{app.extra.owner_names || "No cached owners"}</span>
                </div>
              </section>
              ))}
            </div>
          </div>
        )}
      </SectionFrame>
    </div>
  );
}
