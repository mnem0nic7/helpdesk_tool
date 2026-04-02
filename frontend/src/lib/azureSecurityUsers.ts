import type { AzureDirectoryObject } from "./api.ts";

export function daysSince(iso: string): number {
  if (!iso) return 0;
  const timestamp = new Date(iso).getTime();
  if (Number.isNaN(timestamp)) return 0;
  return Math.floor((Date.now() - timestamp) / 86_400_000);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function getDirectoryLabel(user: AzureDirectoryObject): string {
  if (user.extra.on_prem_domain) return user.extra.on_prem_domain;
  if (user.extra.user_type === "Guest") return "External";
  return "Cloud";
}

export function accountClassLabel(user: AzureDirectoryObject): string {
  if (user.extra.account_class === "shared_or_service") return "Shared / Service";
  if (user.extra.account_class === "guest_external") return "Guest";
  if (user.extra.account_class === "person_synced") return "Person (On-Prem Synced)";
  return "Person";
}

export function priorityScore(user: AzureDirectoryObject): number {
  return Number(user.extra.priority_score || 0);
}

export function isSharedOrService(user: AzureDirectoryObject): boolean {
  return user.extra.account_class === "shared_or_service";
}

export function missingFieldLabel(user: AzureDirectoryObject): string {
  return user.extra.missing_profile_fields || "";
}

export function isLicensedUser(user: AzureDirectoryObject): boolean {
  return String(user.extra.is_licensed || "").toLowerCase() === "true";
}

export function licenseCount(user: AzureDirectoryObject): number {
  const raw = Number(user.extra.license_count || "0");
  return Number.isFinite(raw) ? raw : 0;
}

export function lastSuccessfulIso(user: AzureDirectoryObject): string {
  return user.extra.last_successful_utc || "";
}

export function lastSuccessfulText(user: AzureDirectoryObject): string {
  return user.extra.last_successful_local || formatDateTime(user.extra.last_successful_utc);
}

export function hasNoSuccessfulSignIn(user: AzureDirectoryObject, days = 30): boolean {
  if (user.enabled !== true) return false;
  const iso = lastSuccessfulIso(user);
  if (!iso) return true;
  const timestamp = new Date(iso).getTime();
  if (Number.isNaN(timestamp)) return true;
  return Date.now() - timestamp >= days * 24 * 60 * 60 * 1000;
}

export function isOnPremSynced(user: AzureDirectoryObject): boolean {
  return String(user.extra.on_prem_sync || "").toLowerCase() === "true";
}
