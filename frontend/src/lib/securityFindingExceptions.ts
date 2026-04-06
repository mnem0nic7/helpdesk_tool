import type {
  AzureDirectoryObject,
  SecurityFindingException,
  SecurityFindingExceptionFindingKey,
} from "./api.ts";
import {
  hasNoSuccessfulSignIn,
  isLicensedUser,
  isOnPremSynced,
  isSharedOrService,
  priorityScore,
} from "./azureSecurityUsers.ts";

export const DIRECTORY_USER_EXCEPTION_SCOPE = "directory_user";
export const ALL_FINDINGS_EXCEPTION_KEY = "all-findings";

export const SECURITY_FINDING_LABELS: Record<SecurityFindingExceptionFindingKey, string> = {
  "all-findings": "All user-security findings",
  "priority-user": "Priority queue",
  "stale-signin": "Stale sign-ins",
  "disabled-licensed": "Disabled + licensed",
  "guest-user": "Guest users",
  "on-prem-synced": "On-prem synced",
  "shared-service": "Shared / service",
};

export type UserReviewFindingFocus = "all" | "priority" | "stale" | "disabled-licensed" | "guests" | "synced" | "shared-service";

const USER_REVIEW_FOCUS_KEYS: Record<Exclude<UserReviewFindingFocus, "all">, SecurityFindingExceptionFindingKey> = {
  priority: "priority-user",
  stale: "stale-signin",
  "disabled-licensed": "disabled-licensed",
  guests: "guest-user",
  synced: "on-prem-synced",
  "shared-service": "shared-service",
};

export function getSecurityFindingLabel(findingKey: SecurityFindingExceptionFindingKey): string {
  return SECURITY_FINDING_LABELS[findingKey] || SECURITY_FINDING_LABELS["all-findings"];
}

export function buildSecurityFindingExceptionIndex(
  exceptions: SecurityFindingException[],
): Map<string, Map<SecurityFindingExceptionFindingKey, SecurityFindingException>> {
  const index = new Map<string, Map<SecurityFindingExceptionFindingKey, SecurityFindingException>>();
  for (const exception of exceptions) {
    if (exception.status !== "active" || !exception.entity_id) continue;
    const existing = index.get(exception.entity_id) ?? new Map<SecurityFindingExceptionFindingKey, SecurityFindingException>();
    existing.set(exception.finding_key, exception);
    index.set(exception.entity_id, existing);
  }
  return index;
}

export function getSecurityFindingException(
  exceptionIndex: Map<string, Map<SecurityFindingExceptionFindingKey, SecurityFindingException>>,
  entityId: string,
  findingKey: SecurityFindingExceptionFindingKey,
): SecurityFindingException | null {
  const entityExceptions = exceptionIndex.get(entityId);
  if (!entityExceptions) return null;
  return entityExceptions.get(findingKey) ?? entityExceptions.get(ALL_FINDINGS_EXCEPTION_KEY) ?? null;
}

export function hasSecurityFindingException(
  exceptionIndex: Map<string, Map<SecurityFindingExceptionFindingKey, SecurityFindingException>>,
  entityId: string,
  findingKey: SecurityFindingExceptionFindingKey,
): boolean {
  return getSecurityFindingException(exceptionIndex, entityId, findingKey) !== null;
}

export function matchingUserReviewFindingKeys(user: AzureDirectoryObject): SecurityFindingExceptionFindingKey[] {
  const keys: SecurityFindingExceptionFindingKey[] = [];
  if (priorityScore(user) >= 60) keys.push("priority-user");
  if (hasNoSuccessfulSignIn(user)) keys.push("stale-signin");
  if (user.enabled === false && isLicensedUser(user)) keys.push("disabled-licensed");
  if (user.extra.user_type === "Guest") keys.push("guest-user");
  if (isOnPremSynced(user)) keys.push("on-prem-synced");
  if (isSharedOrService(user)) keys.push("shared-service");
  return keys;
}

export function defaultUserReviewFindingKey(
  focus: UserReviewFindingFocus,
  user: AzureDirectoryObject,
): SecurityFindingExceptionFindingKey {
  if (focus !== "all") {
    const preferred = USER_REVIEW_FOCUS_KEYS[focus];
    if (matchingUserReviewFindingKeys(user).includes(preferred)) {
      return preferred;
    }
  }
  return matchingUserReviewFindingKeys(user)[0] ?? "priority-user";
}

export function findingOptionsForUserReview(
  user: AzureDirectoryObject,
): Array<{ key: SecurityFindingExceptionFindingKey; label: string }> {
  return matchingUserReviewFindingKeys(user).map((key) => ({
    key,
    label: getSecurityFindingLabel(key),
  }));
}
