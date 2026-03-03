import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type { TicketRow } from "../lib/api.ts";
import SLAComplianceCard from "../components/SLAComplianceCard.tsx";

// ---------------------------------------------------------------------------
// Priority badge color helper
// ---------------------------------------------------------------------------

function priorityColor(priority: string): string {
  switch (priority.toLowerCase()) {
    case "highest":
      return "bg-red-100 text-red-800";
    case "high":
      return "bg-orange-100 text-orange-800";
    case "medium":
      return "bg-yellow-100 text-yellow-800";
    case "low":
      return "bg-blue-100 text-blue-800";
    case "lowest":
      return "bg-gray-100 text-gray-700";
    default:
      return "bg-gray-100 text-gray-700";
  }
}

// ---------------------------------------------------------------------------
// SLA status badge helper
// ---------------------------------------------------------------------------

function slaStatusBadge(status: string): string {
  const s = status.toLowerCase();
  if (s.includes("breached")) return "bg-red-100 text-red-800";
  if (s.includes("met") || s.includes("completed")) return "bg-green-100 text-green-800";
  if (s.includes("paused")) return "bg-yellow-100 text-yellow-800";
  if (s.includes("running") || s.includes("ongoing")) return "bg-blue-100 text-blue-800";
  return "bg-gray-100 text-gray-700";
}

// ---------------------------------------------------------------------------
// Breached Tickets Table (inline fallback since TicketTable may not exist yet)
// ---------------------------------------------------------------------------

function BreachedTicketsTable({ tickets }: { tickets: TicketRow[] }) {
  if (tickets.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-gray-500">
        No breached tickets found.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-semibold tracking-wider text-gray-600 uppercase">
              Key
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold tracking-wider text-gray-600 uppercase">
              Summary
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold tracking-wider text-gray-600 uppercase">
              Status
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold tracking-wider text-gray-600 uppercase">
              Priority
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold tracking-wider text-gray-600 uppercase">
              Assignee
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold tracking-wider text-gray-600 uppercase">
              SLA Response
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold tracking-wider text-gray-600 uppercase">
              SLA Resolution
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {tickets.map((ticket) => (
            <tr key={ticket.key} className="hover:bg-gray-50">
              <td className="whitespace-nowrap px-4 py-3 font-medium text-blue-700">
                {ticket.key}
              </td>
              <td className="max-w-xs truncate px-4 py-3 text-gray-800" title={ticket.summary}>
                {ticket.summary}
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-gray-700">
                {ticket.status}
              </td>
              <td className="whitespace-nowrap px-4 py-3">
                <span
                  className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${priorityColor(ticket.priority)}`}
                >
                  {ticket.priority}
                </span>
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-gray-700">
                {ticket.assignee || "Unassigned"}
              </td>
              <td className="whitespace-nowrap px-4 py-3">
                <span
                  className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${slaStatusBadge(ticket.sla_first_response_status)}`}
                >
                  {ticket.sla_first_response_status || "N/A"}
                </span>
              </td>
              <td className="whitespace-nowrap px-4 py-3">
                <span
                  className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${slaStatusBadge(ticket.sla_resolution_status)}`}
                >
                  {ticket.sla_resolution_status || "N/A"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SLA Page
// ---------------------------------------------------------------------------

export default function SLAPage() {
  const {
    data: timers,
    isLoading: loadingSummary,
    error: summaryError,
  } = useQuery({
    queryKey: ["sla-summary"],
    queryFn: api.getSLASummary,
  });

  const {
    data: breaches,
    isLoading: loadingBreaches,
    error: breachesError,
  } = useQuery({
    queryKey: ["sla-breaches"],
    queryFn: api.getSLABreaches,
  });

  // ---- Loading state ----
  if (loadingSummary || loadingBreaches) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
        <p className="mt-4 text-sm text-gray-500">Loading SLA data...</p>
      </div>
    );
  }

  // ---- Error state ----
  if (summaryError || breachesError) {
    const msg =
      (summaryError as Error)?.message ||
      (breachesError as Error)?.message ||
      "Unknown error";
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6">
        <h2 className="text-lg font-semibold text-red-800">
          Failed to load SLA data
        </h2>
        <p className="mt-2 text-sm text-red-700">{msg}</p>
      </div>
    );
  }

  const timerList = timers ?? [];
  const breachList = breaches ?? [];

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">SLA Tracker</h1>
        <p className="mt-1 text-sm text-gray-500">
          Monitor SLA compliance rates and track breached tickets.
        </p>
      </div>

      {/* SLA Compliance Cards Grid */}
      {timerList.length > 0 ? (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
          {timerList.map((timer) => (
            <SLAComplianceCard key={timer.timer_name} timer={timer} />
          ))}
        </div>
      ) : (
        <div className="rounded-lg bg-white p-6 text-center text-sm text-gray-500 shadow">
          No SLA timer data available.
        </div>
      )}

      {/* Breached Tickets Section */}
      <div className="rounded-lg bg-white shadow">
        <div className="flex items-center gap-3 border-b border-gray-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-gray-900">
            Breached Tickets
          </h2>
          <span className="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800">
            {breachList.length}
          </span>
        </div>
        <BreachedTicketsTable tickets={breachList} />
      </div>
    </div>
  );
}
