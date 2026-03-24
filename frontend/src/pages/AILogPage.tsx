import { useDeferredValue, useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../lib/api.ts";
import { logClientError } from "../lib/errorLogging.ts";
import type { TriageLogEntry } from "../lib/api.ts";
import TicketWorkbenchDrawer from "../components/TicketWorkbenchDrawer.tsx";
import useTicketDrawerNavigation from "../hooks/useTicketDrawerNavigation.ts";

const PAGE_SIZE = 20;

const fieldLabels: Record<string, string> = {
  priority: "Priority",
  request_type: "Request Type",
  status: "Status",
  assignee: "Assignee",
  comment: "Comment",
};

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function AILogPage() {
  const queryClient = useQueryClient();
  const { ticketKey, buildTicketHref, closeTicket } = useTicketDrawerNavigation();
  const [starting, setStarting] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: "error" | "info" } | null>(null);
  const [scoreStarting, setScoreStarting] = useState(false);
  const [scoreMessage, setScoreMessage] = useState<{ text: string; type: "error" | "info" } | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const deferredSearchQuery = useDeferredValue(searchQuery.trim());

  // Always poll run status so progress survives navigation
  const { data: runStatus } = useQuery({
    queryKey: ["triage-run-status"],
    queryFn: () => api.getTriageRunStatus(),
    refetchInterval: 2_000,
  });
  const { data: scoreRunStatus } = useQuery({
    queryKey: ["technician-score-run-status"],
    queryFn: () => api.getTechnicianScoreRunStatus(),
    refetchInterval: 2_000,
  });

  const isRunning = runStatus?.running ?? false;
  const isScoring = scoreRunStatus?.running ?? false;
  const technicianScoringPriorityBlocked = Boolean(scoreRunStatus?.priority_blocked);
  const technicianScoringBlockedMessage = scoreRunStatus?.priority_message?.trim() || "";

  const cancelRun = useMutation({
    mutationFn: () => api.cancelTriageRun(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["triage-run-status"] });
    },
  });
  const cancelScoreRun = useMutation({
    mutationFn: () => api.cancelTechnicianScoreRun(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["technician-score-run-status"] });
    },
  });

  async function handleRun(limit?: number, reset?: boolean, reprocess?: boolean) {
    setStarting(true);
    setMessage(null);
    try {
      const res = await api.runTriageAll(undefined, limit, reset, reprocess);
      if (res.total_tickets === 0) {
        const msg = reprocess
          ? "No previously processed tickets found."
          : "All tickets have already been processed. Use \u201cReprocess Done\u201d or \u201cRerun All\u201d.";
        setMessage({ text: msg, type: "info" });
      }
      queryClient.invalidateQueries({ queryKey: ["triage-run-status"] });
    } catch (err) {
      logClientError("Failed to run triage", err, {
        limit,
        reset,
        reprocess,
      });
      setMessage({ text: `Error: ${err instanceof Error ? err.message : String(err)}`, type: "error" });
    } finally {
      setStarting(false);
    }
  }

  async function handleScoreClosedTickets() {
    setScoreStarting(true);
    setScoreMessage(null);
    try {
      const res = await api.runClosedTicketScoring();
      if (res.total_tickets === 0) {
        setScoreMessage({
          text: "All closed tickets already have technician QA scores.",
          type: "info",
        });
      }
      queryClient.invalidateQueries({ queryKey: ["technician-score-run-status"] });
    } catch (err) {
      logClientError("Failed to score closed tickets", err);
      setScoreMessage({
        text: `Error: ${err instanceof Error ? err.message : String(err)}`,
        type: "error",
      });
    } finally {
      setScoreStarting(false);
    }
  }

  const { data: log, isLoading } = useQuery({
    queryKey: ["triage-log", deferredSearchQuery],
    queryFn: () => api.getTriageLog({ search: deferredSearchQuery }),
    placeholderData: (prev) => prev,
    refetchInterval: isRunning ? 5_000 : 30_000,
  });

  const entries = log ?? [];
  const filteredEntries = entries;
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const activeSearchLabel = deferredSearchQuery || searchQuery.trim();

  // Reset visible count when data changes
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [filteredEntries.length, deferredSearchQuery]);

  const loadMore = useCallback(() => {
    setVisibleCount((prev) => Math.min(prev + PAGE_SIZE, filteredEntries.length));
  }, [filteredEntries.length]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) loadMore(); },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loadMore, visibleCount]);

  const visibleEntries = filteredEntries.slice(0, visibleCount);
  const hasMore = visibleCount < filteredEntries.length;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">AI Change Log</h1>
          <p className="mt-1 text-sm text-gray-500">
            All changes made by AI triage — both automatic and user-approved.
          </p>
        </div>
        <div className="flex gap-2">
          {isRunning ? (
            <button
              onClick={() => cancelRun.mutate()}
              disabled={cancelRun.isPending}
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {cancelRun.isPending ? "Stopping…" : "Stop"}
            </button>
          ) : (
            <>
              <button
                onClick={() => handleRun(10, false)}
                disabled={starting}
                className="rounded-lg bg-gray-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {starting ? "Starting…" : "Test (10 Tickets)"}
              </button>
              <button
                onClick={() => handleRun(undefined, false)}
                disabled={starting}
                className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {starting ? "Starting…" : `Run Remaining (${runStatus?.remaining_count?.toLocaleString() ?? "…"})`}
              </button>
              <button
                onClick={() => handleRun(undefined, false, true)}
                disabled={starting}
                className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {starting ? "Starting…" : `Reprocess Done (${runStatus?.processed_count?.toLocaleString() ?? "…"})`}
              </button>
              <button
                onClick={() => handleRun(undefined, true)}
                disabled={starting}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {starting ? "Starting…" : "Rerun All Tickets"}
              </button>
            </>
          )}
        </div>
      </div>
      {message && (
        <div className={`rounded-lg px-4 py-3 text-sm ${message.type === "error" ? "bg-red-50 text-red-700" : "bg-yellow-50 text-yellow-700"}`}>
          {message.text}
        </div>
      )}
      {isRunning && runStatus && runStatus.total > 0 && (
        <div className="rounded-lg px-4 py-3 text-sm bg-blue-50 text-blue-700">
          <div className="flex items-center justify-between text-xs mb-1">
            <span>Processing {runStatus.current_key ?? "…"} ({runStatus.processed}/{runStatus.total})</span>
            <span>{Math.round((runStatus.processed / runStatus.total) * 100)}%</span>
          </div>
          <div className="h-2 w-full rounded-full bg-blue-200">
            <div
              className="h-2 rounded-full bg-blue-600 transition-all duration-500"
              style={{ width: `${(runStatus.processed / runStatus.total) * 100}%` }}
            />
          </div>
        </div>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Search AI Activity</h2>
            <p className="mt-1 text-sm text-slate-500">
              Search AI triage changes by ticket, summary, field, model, source, and notes.
            </p>
          </div>
          <div className="w-full max-w-xl">
            <label htmlFor="ai-log-search" className="sr-only">Search AI log</label>
            <div className="flex gap-2">
              <input
                id="ai-log-search"
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search ticket, summary, field, model, user, or notes…"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
                >
                  Clear
                </button>
              )}
            </div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
          <span className="rounded-full bg-slate-100 px-3 py-1">
            Change matches: {filteredEntries.length.toLocaleString()}
          </span>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Technician QA Scoring</h2>
            <p className="mt-1 text-sm text-slate-500">
              Run AI reviews for closed tickets here. Open an individual ticket to view the actual technician QA score and notes.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
              Closed scored: {scoreRunStatus?.processed_count?.toLocaleString() ?? "…"}
            </span>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
              Remaining closed: {scoreRunStatus?.remaining_count?.toLocaleString() ?? "…"}
            </span>
            {isScoring ? (
              <button
                onClick={() => cancelScoreRun.mutate()}
                disabled={cancelScoreRun.isPending}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {cancelScoreRun.isPending ? "Stopping…" : "Stop Scoring"}
              </button>
            ) : (
              <button
                onClick={() => handleScoreClosedTickets()}
                disabled={scoreStarting || technicianScoringPriorityBlocked}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {scoreStarting ? "Starting…" : `Score Closed Tickets (${scoreRunStatus?.remaining_count?.toLocaleString() ?? "…"})`}
              </button>
            )}
          </div>
        </div>

        {!isScoring && technicianScoringPriorityBlocked && technicianScoringBlockedMessage && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            {technicianScoringBlockedMessage}
          </div>
        )}

        {scoreMessage && (
          <div className={`mt-4 rounded-lg px-4 py-3 text-sm ${scoreMessage.type === "error" ? "bg-red-50 text-red-700" : "bg-yellow-50 text-yellow-700"}`}>
            {scoreMessage.text}
          </div>
        )}

        {isScoring && scoreRunStatus && scoreRunStatus.total > 0 && (
          <div className="mt-4 rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-700">
            <div className="mb-1 flex items-center justify-between text-xs">
              <span>
                Scoring {scoreRunStatus.current_key ?? "…"} ({scoreRunStatus.processed}/{scoreRunStatus.total})
              </span>
              <span>{Math.round((scoreRunStatus.processed / scoreRunStatus.total) * 100)}%</span>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-200">
              <div
                className="h-2 rounded-full bg-slate-900 transition-all duration-500"
                style={{ width: `${(scoreRunStatus.processed / scoreRunStatus.total) * 100}%` }}
              />
            </div>
          </div>
        )}
      </section>

      <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
        <div className="max-h-[75vh] overflow-y-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Ticket</th>
                <th className="px-4 py-3">Field</th>
                <th className="px-4 py-3">Change</th>
                <th className="px-4 py-3">Confidence</th>
                <th className="px-4 py-3">Model</th>
                <th className="px-4 py-3">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {isLoading && (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-gray-400">
                    Loading log…
                  </td>
                </tr>
              )}
              {!isLoading && filteredEntries.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-gray-400">
                    {activeSearchLabel
                      ? `No AI changes match "${activeSearchLabel}".`
                      : "No AI changes recorded yet."}
                  </td>
                </tr>
              )}
              {visibleEntries.map((e: TriageLogEntry, i: number) => (
                <tr key={`${e.key}-${e.field}-${i}`} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-2.5 text-gray-500">
                    {formatTimestamp(e.timestamp)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 font-medium">
                    <Link
                      to={buildTicketHref(e.key)}
                      className="text-blue-600 hover:underline"
                    >
                      {e.key}
                    </Link>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-gray-700">
                    {fieldLabels[e.field] ?? e.field}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="text-gray-400">{e.old_value || "—"}</span>
                    <span className="mx-1.5 text-gray-300">&rarr;</span>
                    <span className="font-medium text-gray-900">{e.new_value}</span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                        e.confidence >= 0.8
                          ? "bg-green-100 text-green-700"
                          : e.confidence >= 0.6
                            ? "bg-yellow-100 text-yellow-700"
                            : "bg-red-100 text-red-700"
                      }`}
                    >
                      {Math.round(e.confidence * 100)}%
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-gray-500 text-xs">
                    {e.model}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5">
                    {e.source === "auto" ? (
                      <span className="inline-block rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
                        Auto
                      </span>
                    ) : (
                      <span className="inline-block rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">
                        {e.approved_by || "User"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {hasMore && (
            <div ref={sentinelRef} className="px-4 py-3 text-center text-xs text-gray-400">
              Showing {visibleCount} of {filteredEntries.length} entries — scroll for more
            </div>
          )}
        </div>
      </div>

      <TicketWorkbenchDrawer
        ticketKey={ticketKey}
        onClose={closeTicket}
      />
    </div>
  );
}
