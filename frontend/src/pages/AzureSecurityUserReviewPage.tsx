import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import { AzureSecurityLaneHero, AzureSecurityMetricCard, LaneSummaryPanel } from "../components/AzureSecurityLane.tsx";
import {
  api,
  type AzureDirectoryObject,
  type SecurityFindingException,
  type SecurityFindingExceptionFindingKey,
} from "../lib/api.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";
import SecurityReviewPagination, { sliceSecurityReviewPage, useSecurityReviewPagination } from "../components/SecurityReviewPagination.tsx";
import {
  accountClassLabel,
  getDirectoryLabel,
  hasNoSuccessfulSignIn,
  isLicensedUser,
  isOnPremSynced,
  isSharedOrService,
  lastSuccessfulText,
  licenseCount,
  missingFieldLabel,
  priorityScore,
} from "../lib/azureSecurityUsers.ts";
import {
  buildSecurityFindingExceptionIndex,
  defaultUserReviewFindingKey,
  DIRECTORY_USER_EXCEPTION_SCOPE,
  findingOptionsForUserReview,
  getSecurityFindingException,
  getSecurityFindingLabel,
  hasSecurityFindingException,
  matchingUserReviewFindingKeys,
} from "../lib/securityFindingExceptions.ts";

type UserFocus = "all" | "priority" | "stale" | "disabled-licensed" | "guests" | "synced" | "shared-service";
type ExceptionNotice = { tone: "success" | "error"; text: string } | null;

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

function buildUserRoute(userId: string): string {
  return `/users?userId=${encodeURIComponent(userId)}`;
}

function userFlags(user: AzureDirectoryObject): string[] {
  const flags: string[] = [];
  if (user.enabled === false) flags.push("Disabled account");
  if (isLicensedUser(user)) flags.push(`${licenseCount(user)} active license${licenseCount(user) === 1 ? "" : "s"}`);
  if (hasNoSuccessfulSignIn(user)) flags.push("No successful sign-in in 30+ days");
  if (user.extra.user_type === "Guest") flags.push("Guest user");
  if (isOnPremSynced(user)) flags.push("On-prem synced");
  if (isSharedOrService(user)) flags.push("Shared / service-style account");
  if (missingFieldLabel(user)) flags.push(`Missing ${missingFieldLabel(user)}`);
  return flags;
}

function isExceptionEligible(user: AzureDirectoryObject): boolean {
  return matchingUserReviewFindingKeys(user).length > 0;
}

function actorLabel(exception: SecurityFindingException): string {
  return exception.updated_by_name || exception.updated_by_email || exception.created_by_name || exception.created_by_email || "Unknown operator";
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

function FindingExceptionDrawer({
  user,
  flags,
  findingOptions,
  findingKey,
  existingException,
  reason,
  isSaving,
  onFindingKeyChange,
  onReasonChange,
  onClose,
  onSave,
}: {
  user: AzureDirectoryObject | null;
  flags: string[];
  findingOptions: Array<{ key: SecurityFindingExceptionFindingKey; label: string }>;
  findingKey: SecurityFindingExceptionFindingKey;
  existingException: SecurityFindingException | null;
  reason: string;
  isSaving: boolean;
  onFindingKeyChange: (value: SecurityFindingExceptionFindingKey) => void;
  onReasonChange: (value: string) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const reasonInputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!user) return undefined;

    const previousOverflow = document.body.style.overflow;
    const focusTimer = window.setTimeout(() => reasonInputRef.current?.focus(), 0);
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose, user]);

  if (!user) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/35 backdrop-blur-[1px]" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="security-finding-exception-drawer-title"
        aria-describedby="security-finding-exception-drawer-description"
        data-testid="security-finding-exception-drawer"
        className="flex h-full w-full max-w-2xl flex-col overflow-hidden bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="border-b border-slate-200 px-6 py-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Security finding exception</div>
              <h2 id="security-finding-exception-drawer-title" className="mt-1 text-2xl font-semibold text-slate-900">
                Mark finding as exception
              </h2>
              <p id="security-finding-exception-drawer-description" className="mt-2 max-w-xl text-sm text-slate-600">
                Approved exceptions stay out of User Review, Guest Access Review, Account Health, and the shared workspace summary until you restore them.
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Cancel
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-6">
          <section className="rounded-2xl border border-slate-200 bg-slate-50/80 p-5">
            <div className="text-base font-semibold text-slate-900">{user.display_name}</div>
            <div className="mt-1 text-sm text-slate-500">{user.principal_name || user.mail || user.id}</div>
            <div className="mt-4 flex flex-wrap gap-2">
              {flags.map((flag) => (
                <span key={`${user.id}-${flag}`} className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-700 shadow-sm ring-1 ring-slate-200">
                  {flag}
                </span>
              ))}
            </div>
          </section>

          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Exception applies to</span>
            <select
              value={findingKey}
              onChange={(event) => onFindingKeyChange(event.target.value as SecurityFindingExceptionFindingKey)}
              className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
            >
              {findingOptions.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Exception reason</span>
            <textarea
              ref={reasonInputRef}
              value={reason}
              onChange={(event) => onReasonChange(event.target.value)}
              rows={8}
              placeholder="Document why this finding is expected or approved so it can stay out of recurring security reports."
              className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
            />
          </label>
          <p className="text-xs text-slate-500">
            {existingException
              ? `This ${existingException.finding_label.toLowerCase()} exception already exists. Saving will update its reason.`
              : "Exceptions require a reason so future reviews can understand why the finding was suppressed."}
          </p>
        </div>

        <div className="border-t border-slate-200 bg-white px-6 py-4">
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={onSave}
              disabled={isSaving || reason.trim().length === 0}
              className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSaving ? "Saving exception..." : existingException ? "Update exception" : "Save exception"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Keep in review queue
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
}

export default function AzureSecurityUserReviewPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [focus, setFocus] = useState<UserFocus>("priority");
  const [exceptionDraftUser, setExceptionDraftUser] = useState<AzureDirectoryObject | null>(null);
  const [exceptionDraftFindingKey, setExceptionDraftFindingKey] = useState<SecurityFindingExceptionFindingKey>("priority-user");
  const [exceptionReason, setExceptionReason] = useState("");
  const [exceptionNotice, setExceptionNotice] = useState<ExceptionNotice>(null);
  const deferredSearch = useDeferredValue(search);

  const usersQuery = useQuery({
    queryKey: ["azure", "users", { search: "" }],
    queryFn: () => api.getAzureUsers(""),
    ...getPollingQueryOptions("slow_5m"),
  });
  const statusQuery = useQuery({
    queryKey: ["azure", "status"],
    queryFn: () => api.getAzureStatus(),
    ...getPollingQueryOptions("slow_5m"),
  });
  const exceptionsQuery = useQuery({
    queryKey: ["azure", "security", "finding-exceptions", DIRECTORY_USER_EXCEPTION_SCOPE],
    queryFn: () => api.getAzureSecurityFindingExceptions(DIRECTORY_USER_EXCEPTION_SCOPE),
    ...getPollingQueryOptions("slow_5m"),
  });

  const activeExceptions = exceptionsQuery.data ?? [];
  const exceptionIndex = useMemo(
    () => buildSecurityFindingExceptionIndex(activeExceptions),
    [activeExceptions],
  );
  const users = usersQuery.data ?? EMPTY_DIRECTORY_OBJECTS;

  const invalidateSecurityFindingViews = () => {
    queryClient.invalidateQueries({ queryKey: ["azure", "security", "finding-exceptions", DIRECTORY_USER_EXCEPTION_SCOPE] }).catch(() => undefined);
    queryClient.invalidateQueries({ queryKey: ["azure", "security", "workspace-summary"] }).catch(() => undefined);
  };

  const createExceptionMutation = useMutation({
    mutationFn: (body: { user: AzureDirectoryObject; reason: string; findingKey: SecurityFindingExceptionFindingKey }) =>
      api.createAzureSecurityFindingException({
        scope: DIRECTORY_USER_EXCEPTION_SCOPE,
        finding_key: body.findingKey,
        finding_label: getSecurityFindingLabel(body.findingKey),
        entity_id: body.user.id,
        entity_label: body.user.display_name,
        entity_subtitle: body.user.principal_name || body.user.mail || body.user.id,
        reason: body.reason,
      }),
    onSuccess: (exception) => {
      setExceptionNotice({
        tone: "success",
        text: `${exception.entity_label || "This finding"} is now an active ${exception.finding_label.toLowerCase()} exception.`,
      });
      setExceptionDraftUser(null);
      setExceptionReason("");
      invalidateSecurityFindingViews();
    },
    onError: (error) => {
      setExceptionNotice({
        tone: "error",
        text: error instanceof Error ? error.message : "Failed to save the security finding exception.",
      });
    },
  });

  const restoreExceptionMutation = useMutation({
    mutationFn: (exception: SecurityFindingException) => api.restoreAzureSecurityFindingException(exception.exception_id),
    onSuccess: (exception) => {
      setExceptionNotice({
        tone: "success",
        text: `${exception.entity_label || "The finding"} was restored to the security review queues.`,
      });
      invalidateSecurityFindingViews();
    },
    onError: (error) => {
      setExceptionNotice({
        tone: "error",
        text: error instanceof Error ? error.message : "Failed to restore the security finding.",
      });
    },
  });

  const hasFindingException = useCallback(
    (userId: string, findingKey: SecurityFindingExceptionFindingKey) =>
      hasSecurityFindingException(exceptionIndex, userId, findingKey),
    [exceptionIndex],
  );

  // Single pass: compute all counts + priority queue, with a score cache reused
  // by filteredUsers to avoid calling priorityScore O(n log n) times in the sort.
  const { disabledLicensedCount, staleSignInCount, guestCount, onPremCount, sharedServiceCount, priorityQueue, scoreCache } = useMemo(() => {
    const scoreCache = new Map<string, number>();
    const score = (user: AzureDirectoryObject) => {
      let s = scoreCache.get(user.id);
      if (s === undefined) { s = priorityScore(user); scoreCache.set(user.id, s); }
      return s;
    };

    let disabledLicensedCount = 0;
    let staleSignInCount = 0;
    let guestCount = 0;
    let onPremCount = 0;
    let sharedServiceCount = 0;
    const priorityCandidates: AzureDirectoryObject[] = [];

    for (const user of users) {
      if (user.enabled === false && isLicensedUser(user) && !hasFindingException(user.id, "disabled-licensed")) disabledLicensedCount++;
      if (hasNoSuccessfulSignIn(user) && !hasFindingException(user.id, "stale-signin")) staleSignInCount++;
      if (user.extra.user_type === "Guest" && !hasFindingException(user.id, "guest-user")) guestCount++;
      if (isOnPremSynced(user) && !hasFindingException(user.id, "on-prem-synced")) onPremCount++;
      if (isSharedOrService(user) && !hasFindingException(user.id, "shared-service")) sharedServiceCount++;
      if (score(user) >= 60 && !hasFindingException(user.id, "priority-user")) priorityCandidates.push(user);
    }

    priorityCandidates.sort((a, b) => score(b) - score(a) || a.display_name.localeCompare(b.display_name));

    return { disabledLicensedCount, staleSignInCount, guestCount, onPremCount, sharedServiceCount, priorityQueue: priorityCandidates.slice(0, 8), scoreCache };
  }, [hasFindingException, users]);

  const filteredUsers = useMemo(() => {
    const score = (user: AzureDirectoryObject) => scoreCache.get(user.id) ?? priorityScore(user);
    const sorted = [...users].sort(
      (left, right) => score(right) - score(left) || left.display_name.localeCompare(right.display_name),
    );
    return sorted.filter((user) => {
      if (focus === "priority" && (score(user) < 60 || hasFindingException(user.id, "priority-user"))) return false;
      if (focus === "stale" && (!hasNoSuccessfulSignIn(user) || hasFindingException(user.id, "stale-signin"))) return false;
      if (
        focus === "disabled-licensed" &&
        (!(user.enabled === false && isLicensedUser(user)) || hasFindingException(user.id, "disabled-licensed"))
      ) {
        return false;
      }
      if (focus === "guests" && (user.extra.user_type !== "Guest" || hasFindingException(user.id, "guest-user"))) return false;
      if (focus === "synced" && (!isOnPremSynced(user) || hasFindingException(user.id, "on-prem-synced"))) return false;
      if (focus === "shared-service" && (!isSharedOrService(user) || hasFindingException(user.id, "shared-service"))) return false;
      if (focus === "all" && hasFindingException(user.id, "all-findings")) return false;
      return matchesSearch(
        [
          user.display_name,
          user.principal_name,
          user.mail,
          user.extra.department,
          user.extra.job_title,
          user.extra.priority_reason,
          userFlags(user),
        ],
        deferredSearch,
      );
    });
  }, [deferredSearch, focus, hasFindingException, scoreCache, users]);
  const reviewPagination = useSecurityReviewPagination(
    `${deferredSearch}|${focus}|${filteredUsers.length}`,
    filteredUsers.length,
  );
  const visibleUsers = useMemo(
    () => sliceSecurityReviewPage(filteredUsers, reviewPagination.pageStart, reviewPagination.pageSize),
    [filteredUsers, reviewPagination.pageSize, reviewPagination.pageStart],
  );
  const closeExceptionDraft = useCallback(() => {
    setExceptionDraftUser(null);
    setExceptionDraftFindingKey("priority-user");
    setExceptionReason("");
  }, []);

  if (usersQuery.isLoading) {
    return <AzurePageSkeleton titleWidth="w-56" subtitleWidth="w-[42rem]" statCount={6} sectionCount={3} />;
  }

  if (usersQuery.isError) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load user review: {usersQuery.error instanceof Error ? usersQuery.error.message : "Unknown error"}
      </div>
    );
  }

  const directoryDataset = statusQuery.data?.datasets?.find((dataset) => dataset.key === "directory");
  const exceptionDraftOptions = exceptionDraftUser ? findingOptionsForUserReview(exceptionDraftUser) : [];
  const exceptionDraftFlags = exceptionDraftUser ? userFlags(exceptionDraftUser) : [];
  const existingDraftException = exceptionDraftUser
    ? getSecurityFindingException(exceptionIndex, exceptionDraftUser.id, exceptionDraftFindingKey)
    : null;

  const startExceptionDraft = (user: AzureDirectoryObject, draftFocus: UserFocus = focus) => {
    const nextFindingKey = defaultUserReviewFindingKey(draftFocus, user);
    const existingException = getSecurityFindingException(exceptionIndex, user.id, nextFindingKey);
    setExceptionDraftUser(user);
    setExceptionDraftFindingKey(nextFindingKey);
    setExceptionReason(existingException?.reason || "");
    setExceptionNotice(null);
  };

  return (
    <div className="space-y-6">
      <AzureSecurityLaneHero
        title="User Review"
        description="Review stale sign-ins, disabled licensed accounts, guest users, synced identities, and shared/service-style accounts from one security-native lane. Use the hidden raw user page only when you need the admin drawer or direct action surface."
        refreshLabel="Directory refresh"
        refreshValue={formatTimestamp(directoryDataset?.last_refresh ?? statusQuery.data?.last_refresh)}
        actions={[
          { label: "Back to Security workspace", to: "/security", tone: "secondary" },
          { label: "Open Account Health", to: "/security/account-health" },
          { label: "Open raw user inventory", to: "/users", tone: "secondary" },
        ]}
      />

      <LaneSummaryPanel laneKey="user-review" />

      {exceptionsQuery.isError ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 shadow-sm">
          Security finding exceptions could not be loaded right now, so approved exceptions may temporarily reappear in this lane and the shared user-security summaries.
        </section>
      ) : null}

      {exceptionNotice ? (
        <section
          className={`rounded-2xl border p-4 text-sm shadow-sm ${
            exceptionNotice.tone === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
              : "border-red-200 bg-red-50 text-red-700"
          }`}
        >
          {exceptionNotice.text}
        </section>
      ) : null}

      <section className="grid gap-4 xl:grid-cols-3 md:grid-cols-2">
        <AzureSecurityMetricCard
          label="Priority queue"
          value={priorityQueue.length}
          detail="High-signal users derived from cached account priority and hygiene heuristics."
          tone="rose"
        />
        <AzureSecurityMetricCard
          label="Stale sign-ins"
          value={staleSignInCount}
          detail="Enabled users with no successful sign-in in the last 30 days."
          tone="amber"
        />
        <AzureSecurityMetricCard
          label="Disabled + licensed"
          value={disabledLicensedCount}
          detail="Disabled users still holding paid licenses that likely need cleanup."
          tone="rose"
        />
        <AzureSecurityMetricCard
          label="Guest users"
          value={guestCount}
          detail="External identities currently cached in the tenant directory."
          tone="violet"
        />
        <AzureSecurityMetricCard
          label="On-prem synced"
          value={onPremCount}
          detail="Users sourced from on-premises AD that often need different remediation paths."
          tone="sky"
        />
        <AzureSecurityMetricCard
          label="Shared / service"
          value={sharedServiceCount}
          detail="Accounts classified from naming and employee-type markers as shared or service-style."
          tone="emerald"
        />
        <AzureSecurityMetricCard
          label="Active exceptions"
          value={activeExceptions.length}
          detail="Approved findings currently suppressed from the shared user-security queues and workspace summary."
          tone="sky"
        />
      </section>

      <SectionFrame
        title="Priority queue"
        description="Highest-signal user records based on stale credentials, guest age, licensing waste, and missing profile data."
        count={priorityQueue.length}
      >
        {priorityQueue.length === 0 ? (
          <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">No priority users were identified from the current cached directory snapshot.</div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {priorityQueue.map((user) => (
              <section key={user.id} className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-lg font-semibold text-slate-900">{user.display_name}</h3>
                      <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
                        {user.extra.priority_band || "review"}
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
                <div className="mt-4 rounded-xl bg-white px-4 py-3 text-sm text-slate-700">{user.extra.priority_reason}</div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {userFlags(user).map((flag) => (
                    <span key={`${user.id}-${flag}`} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                      {flag}
                    </span>
                  ))}
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => startExceptionDraft(user, "priority")}
                    className="inline-flex items-center rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-800 transition hover:bg-amber-100"
                  >
                    Mark exception
                  </button>
                </div>
              </section>
            ))}
          </div>
        )}
      </SectionFrame>

      <SectionFrame
        title="Review queue"
        description="Filter the cached user inventory into the cohort you want to review, then pivot into the raw user page for deeper admin work."
        count={filteredUsers.length}
      >
        <div className="mb-5 grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px]">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search users, departments, risk reasons, or flags..."
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
          />
          <select
            value={focus}
            onChange={(event) => setFocus(event.target.value as UserFocus)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
          >
            <option value="priority">Priority queue</option>
            <option value="all">All users</option>
            <option value="stale">Stale sign-ins</option>
            <option value="disabled-licensed">Disabled + licensed</option>
            <option value="guests">Guest users</option>
            <option value="synced">On-prem synced</option>
            <option value="shared-service">Shared / service</option>
          </select>
        </div>

        <div className="mb-5">
          <SecurityReviewPagination
            count={filteredUsers.length}
            currentPage={reviewPagination.currentPage}
            pageSize={reviewPagination.pageSize}
            setCurrentPage={reviewPagination.setCurrentPage}
            setPageSize={reviewPagination.setPageSize}
            totalPages={reviewPagination.totalPages}
            noun="matching user record(s)"
          />
        </div>

        {filteredUsers.length === 0 ? (
          <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">No users match the current review filters.</div>
        ) : (
          <div className="overflow-auto rounded-xl border border-slate-200">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3">User</th>
                  <th className="px-4 py-3">Account class</th>
                  <th className="px-4 py-3">Directory</th>
                  <th className="px-4 py-3">Last successful sign-in</th>
                  <th className="px-4 py-3">Review flags</th>
                  <th className="px-4 py-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {visibleUsers.map((user, index) => (
                  <tr key={user.id} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-900">{user.display_name}</div>
                      <div className="mt-1 text-xs text-slate-500">{user.principal_name || user.mail || user.id}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-700">{accountClassLabel(user)}</td>
                    <td className="px-4 py-3 text-slate-700">{getDirectoryLabel(user)}</td>
                    <td className="px-4 py-3 text-slate-700">{lastSuccessfulText(user)}</td>
                    <td className="px-4 py-3">
                      <div className="flex max-w-xl flex-wrap gap-2">
                        {userFlags(user).map((flag) => (
                          <span key={`${user.id}-${flag}`} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                            {flag}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-2">
                        <Link
                          to={buildUserRoute(user.id)}
                          className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                        >
                          Open source record
                        </Link>
                        {isExceptionEligible(user) ? (
                          <button
                            type="button"
                            onClick={() => startExceptionDraft(user, focus)}
                            className="inline-flex items-center rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-800 transition hover:bg-amber-100"
                          >
                            Mark exception
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionFrame>

      <SectionFrame
        title="Active exceptions"
        description="Approved user findings hidden from the shared user-security reports until you restore them."
        count={activeExceptions.length}
      >
        {activeExceptions.length === 0 ? (
          <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">
            No active exceptions are suppressing user findings right now.
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {activeExceptions.map((exception) => (
              <section key={exception.exception_id} className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-lg font-semibold text-slate-900">{exception.entity_label || exception.entity_id}</h3>
                      <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-800">
                        {exception.finding_label}
                      </span>
                    </div>
                    <div className="mt-1 text-sm text-slate-500">{exception.entity_subtitle || exception.entity_id}</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => restoreExceptionMutation.mutate(exception)}
                    disabled={restoreExceptionMutation.isPending}
                    className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {restoreExceptionMutation.isPending ? "Restoring..." : "Restore finding"}
                  </button>
                </div>
                <div className="mt-4 rounded-xl bg-white px-4 py-3 text-sm text-slate-700">{exception.reason}</div>
                <div className="mt-3 text-xs text-slate-500">
                  Active since {formatTimestamp(exception.created_at)} by {actorLabel(exception)}
                </div>
              </section>
            ))}
          </div>
        )}
      </SectionFrame>

      <FindingExceptionDrawer
        user={exceptionDraftUser}
        flags={exceptionDraftFlags}
        findingOptions={exceptionDraftOptions}
        findingKey={exceptionDraftFindingKey}
        existingException={existingDraftException}
        reason={exceptionReason}
        isSaving={createExceptionMutation.isPending}
        onFindingKeyChange={(nextFindingKey) => {
          if (!exceptionDraftUser) return;
          setExceptionDraftFindingKey(nextFindingKey);
          setExceptionReason(getSecurityFindingException(exceptionIndex, exceptionDraftUser.id, nextFindingKey)?.reason || "");
        }}
        onReasonChange={setExceptionReason}
        onClose={closeExceptionDraft}
        onSave={() => {
          if (!exceptionDraftUser) return;
          createExceptionMutation.mutate({
            user: exceptionDraftUser,
            reason: exceptionReason,
            findingKey: exceptionDraftFindingKey,
          });
        }}
      />
    </div>
  );
}
