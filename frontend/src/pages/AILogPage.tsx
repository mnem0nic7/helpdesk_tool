import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type { TriageLogEntry, CacheStatus } from "../lib/api.ts";

const PAGE_SIZE = 100;

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
  const [starting, setStarting] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: "error" | "info" } | null>(null);

  // Always poll run status so progress survives navigation
  const { data: runStatus } = useQuery({
    queryKey: ["triage-run-status"],
    queryFn: () => api.getTriageRunStatus(),
    refetchInterval: 2_000,
  });

  const isRunning = runStatus?.running ?? false;

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
      setMessage({ text: `Error: ${err instanceof Error ? err.message : String(err)}`, type: "error" });
    } finally {
      setStarting(false);
    }
  }

  const { data: log, isLoading } = useQuery({
    queryKey: ["triage-log"],
    queryFn: () => api.getTriageLog(),
    refetchInterval: isRunning ? 5_000 : 30_000,
  });

  const { data: cacheStatus } = useQuery<CacheStatus>({
    queryKey: ["cache-status"],
    queryFn: () => api.getCacheStatus(),
    staleTime: Infinity,
  });
  const jiraBaseUrl = cacheStatus?.jira_base_url;

  const entries = log ?? [];
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Reset visible count when data changes
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [entries.length]);

  const loadMore = useCallback(() => {
    setVisibleCount((prev) => Math.min(prev + PAGE_SIZE, entries.length));
  }, [entries.length]);

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

  const visibleEntries = entries.slice(0, visibleCount);
  const hasMore = visibleCount < entries.length;

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
          <button
            onClick={() => handleRun(10, false)}
            disabled={starting || isRunning}
            className="rounded-lg bg-gray-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {starting ? "Starting…" : isRunning ? "Running…" : "Test (10 Tickets)"}
          </button>
          <button
            onClick={() => handleRun(undefined, false)}
            disabled={starting || isRunning}
            className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {starting ? "Starting…" : isRunning ? "Running…" : "Run Remaining"}
          </button>
          <button
            onClick={() => handleRun(undefined, false, true)}
            disabled={starting || isRunning}
            className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {starting ? "Starting…" : isRunning ? "Running…" : "Reprocess Done"}
          </button>
          <button
            onClick={() => handleRun(undefined, true)}
            disabled={starting || isRunning}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {starting ? "Starting…" : isRunning ? "Running…" : "Rerun All Tickets"}
          </button>
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
              {!isLoading && entries.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-gray-400">
                    No AI changes recorded yet.
                  </td>
                </tr>
              )}
              {visibleEntries.map((e: TriageLogEntry, i: number) => (
                <tr key={`${e.key}-${e.field}-${i}`} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-2.5 text-gray-500">
                    {formatTimestamp(e.timestamp)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 font-medium">
                    {jiraBaseUrl ? (
                      <a
                        href={`${jiraBaseUrl}/browse/${e.key}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline"
                      >
                        {e.key}
                      </a>
                    ) : (
                      <span className="text-gray-900">{e.key}</span>
                    )}
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
              Showing {visibleCount} of {entries.length} entries — scroll for more
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
