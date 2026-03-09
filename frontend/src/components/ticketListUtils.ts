import type { TicketRow } from "../lib/api.ts";

export function formatTTR(hours: number | null): string {
  if (hours == null) return "\u2014";
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours <= 24) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

export function formatAge(days: number | null): string {
  if (days == null) return "\u2014";
  return `${days.toFixed(1)}d`;
}

export function formatDate(iso: string): string {
  if (!iso) return "\u2014";
  return iso.slice(0, 10);
}

export function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max)}\u2026`;
}

export function statusBadgeClass(status: string): string {
  const s = status.toLowerCase();
  if (s === "done" || s === "resolved" || s === "closed") {
    return "bg-green-100 text-green-800";
  }
  if (s === "in progress" || s === "acknowledged") {
    return "bg-blue-100 text-blue-800";
  }
  if (s.startsWith("waiting")) {
    return "bg-yellow-100 text-yellow-800";
  }
  return "bg-gray-100 text-gray-700";
}

export function priorityClass(priority: string): string {
  const p = priority.toLowerCase();
  if (p === "highest" || p === "high") return "text-red-600 font-semibold";
  if (p === "medium") return "text-yellow-600 font-medium";
  return "text-gray-500";
}

export function slaBadgeClass(sla: string): string {
  const s = sla.toLowerCase();
  if (s === "breached") return "bg-red-100 text-red-800";
  if (s === "met") return "bg-green-100 text-green-800";
  if (s === "running" || s === "ongoing") return "bg-blue-100 text-blue-800";
  if (s === "paused") return "bg-yellow-100 text-yellow-800";
  return "bg-gray-100 text-gray-600";
}

export function priorityRank(priority: string): number {
  switch (priority.toLowerCase()) {
    case "highest":
      return 0;
    case "high":
      return 1;
    case "medium":
      return 2;
    case "low":
      return 3;
    case "lowest":
      return 4;
    default:
      return 5;
  }
}

export type TicketBoardColumnId = "todo" | "in_progress" | "waiting" | "done";

export const TICKET_BOARD_COLUMNS: Array<{
  id: TicketBoardColumnId;
  label: string;
  tone: string;
}> = [
  { id: "todo", label: "To Do", tone: "border-slate-200 bg-slate-50" },
  { id: "in_progress", label: "In Progress", tone: "border-blue-200 bg-blue-50/70" },
  { id: "waiting", label: "Waiting", tone: "border-amber-200 bg-amber-50/80" },
  { id: "done", label: "Done", tone: "border-emerald-200 bg-emerald-50/70" },
];

export function getTicketBoardColumnForStatus(
  status: string,
  statusCategory = "",
): TicketBoardColumnId {
  const normalizedStatus = status.toLowerCase();
  const normalizedCategory = statusCategory.toLowerCase();

  if (
    normalizedStatus.startsWith("waiting") ||
    normalizedStatus.includes("pending") ||
    normalizedStatus.includes("hold")
  ) {
    return "waiting";
  }
  if (
    normalizedCategory === "done" ||
    normalizedStatus === "done" ||
    normalizedStatus === "resolved" ||
    normalizedStatus === "closed" ||
    normalizedStatus === "cancelled" ||
    normalizedStatus === "canceled" ||
    normalizedStatus === "declined" ||
    normalizedStatus === "complete" ||
    normalizedStatus === "completed"
  ) {
    return "done";
  }
  if (
    normalizedCategory === "in progress" ||
    normalizedStatus === "acknowledged" ||
    normalizedStatus === "in progress" ||
    normalizedStatus.includes("progress") ||
    normalizedStatus.includes("investigat") ||
    normalizedStatus.includes("working")
  ) {
    return "in_progress";
  }
  return "todo";
}

export function getTicketBoardColumn(
  ticket: Pick<TicketRow, "status" | "status_category">,
): TicketBoardColumnId {
  return getTicketBoardColumnForStatus(ticket.status, ticket.status_category);
}
