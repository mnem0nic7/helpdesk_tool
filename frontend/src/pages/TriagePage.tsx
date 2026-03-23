import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../lib/api.ts";
import { logClientError } from "../lib/errorLogging.ts";
import type {
  TicketRow,
  TicketQueryParams,
  AIModel,
  TriageResult,
  TriageSuggestion,
} from "../lib/api.ts";
import TicketFilters, {
  emptyFilters,
} from "../components/TicketFilters.tsx";
import type { TicketFilterValues } from "../components/TicketFilters.tsx";
import TicketWorkbenchDrawer from "../components/TicketWorkbenchDrawer.tsx";
import useTicketDrawerNavigation from "../hooks/useTicketDrawerNavigation.ts";

// ---------------------------------------------------------------------------
// Confidence bar component
// ---------------------------------------------------------------------------

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 80 ? "bg-green-500" : pct >= 50 ? "bg-yellow-500" : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-20 rounded-full bg-gray-200">
        <div
          className={`h-2 rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-gray-500">{pct}%</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Suggestion card — immediate accept / decline per field
// ---------------------------------------------------------------------------

function SuggestionCard({
  suggestion,
  issueKey,
  onAccepted,
  onDeclined,
}: {
  suggestion: TriageSuggestion;
  issueKey: string;
  onAccepted: (key: string, field: string) => void;
  onDeclined: (key: string, field: string) => void;
}) {
  const [status, setStatus] = useState<"idle" | "applying" | "applied" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  const fieldLabels: Record<string, string> = {
    priority: "Priority",
    status: "Status",
    assignee: "Assignee",
    reporter: "Reporter",
    comment: "Comment",
    request_type: "Request Type",
  };

  async function handleAccept() {
    setStatus("applying");
    setErrorMsg("");
    try {
      await api.applyTriageField(issueKey, suggestion.field);
      setStatus("applied");
      onAccepted(issueKey, suggestion.field);
    } catch (err) {
      logClientError("Failed to apply triage suggestion", err, {
        issueKey,
        field: suggestion.field,
      });
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "Failed to apply");
    }
  }

  function handleDecline() {
    onDeclined(issueKey, suggestion.field);
  }

  return (
    <div
      className={`rounded-lg border p-3 transition-colors ${
        status === "applied"
          ? "border-green-300 bg-green-50"
          : status === "error"
            ? "border-red-300 bg-red-50"
            : "border-gray-200 bg-white"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">
              {fieldLabels[suggestion.field] ?? suggestion.field}
            </span>
            <ConfidenceBar value={suggestion.confidence} />
          </div>
          <div className="mt-1 flex items-center gap-2 text-sm">
            {suggestion.field !== "comment" && (
              <>
                <span className="text-gray-500">
                  {suggestion.current_value || "Not set"}
                </span>
                <span className="text-gray-400">&rarr;</span>
              </>
            )}
            <span className="font-medium text-gray-900">
              {suggestion.suggested_value}
            </span>
          </div>
          <p className="mt-1 text-xs text-gray-500">{suggestion.reasoning}</p>
          {status === "error" && (
            <p className="mt-1 text-xs text-red-600">{errorMsg}</p>
          )}
          {status === "applied" && (
            <p className="mt-1 text-xs text-green-600">Applied successfully</p>
          )}
        </div>
        <div className="flex shrink-0 gap-1.5">
          {status !== "applied" && (
            <>
              <button
                type="button"
                disabled={status === "applying"}
                onClick={handleAccept}
                className="rounded-md border border-green-500 bg-green-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-green-700 disabled:opacity-50"
              >
                {status === "applying" ? "Applying…" : "Accept"}
              </button>
              <button
                type="button"
                disabled={status === "applying"}
                onClick={handleDecline}
                className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
              >
                Decline
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ticket triage review panel — per-field actions, no batch apply
// ---------------------------------------------------------------------------

function TriageReviewPanel({
  result,
  ticketHrefBuilder,
  onOpenTicket,
  onFieldAccepted,
  onFieldDeclined,
  onDismissAll,
  dismissing,
}: {
  result: TriageResult;
  ticketHrefBuilder: (key: string) => string;
  onOpenTicket: (key: string) => void;
  onFieldAccepted: (key: string, field: string) => void;
  onFieldDeclined: (key: string, field: string) => void;
  onDismissAll: (key: string) => void;
  dismissing: boolean;
}) {
  const keyElement = (
    <Link
      to={ticketHrefBuilder(result.key)}
      onClick={() => onOpenTicket(result.key)}
      className="font-semibold text-blue-600 hover:underline"
    >
      {result.key}
    </Link>
  );

  if (result.suggestions.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
        No changes suggested for {keyElement} — the ticket
        looks well-triaged.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
        <div>
          {keyElement}
          <span className="ml-2 text-xs text-gray-400">
            via {result.model_used}
          </span>
        </div>
        <button
          type="button"
          disabled={dismissing}
          onClick={() => onDismissAll(result.key)}
          className="rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50"
        >
          {dismissing ? "Dismissing…" : "Dismiss All"}
        </button>
      </div>
      <div className="space-y-2 p-4">
        {result.suggestions.map((s) => (
          <SuggestionCard
            key={s.field}
            suggestion={s}
            issueKey={result.key}
            onAccepted={onFieldAccepted}
            onDeclined={onFieldDeclined}
          />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function TriagePage() {
  const queryClient = useQueryClient();
  const { ticketKey, buildTicketHref, closeTicket } = useTicketDrawerNavigation();
  const [openTicket, setOpenTicket] = useState<TicketRow | null>(null);

  // Model selection
  const { data: models, isLoading: modelsLoading } = useQuery({
    queryKey: ["triage-models"],
    queryFn: () => api.getTriageModels(),
  });
  const [selectedModel, setSelectedModel] = useState("");

  // Auto-select first model when loaded
  useEffect(() => {
    if (models && models.length > 0 && !selectedModel) {
      setSelectedModel(models[0].id);
    }
  }, [models, selectedModel]);

  // Filters (default to open only, same as ManagePage)
  const [filters, setFilters] = useState<TicketFilterValues>({
    ...emptyFilters,
    open_only: true,
  });

  const handleFilterChange = useCallback((next: TicketFilterValues) => {
    setFilters(next);
    setSelectedKeys(new Set());
  }, []);

  // Build query params from filters
  const queryParams: TicketQueryParams = {
    ...(filters.search ? { search: filters.search } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.priority ? { priority: filters.priority } : {}),
    ...(filters.issue_type ? { issue_type: filters.issue_type } : {}),
    ...(filters.label ? { label: filters.label } : {}),
    ...(filters.assignee ? { assignee: filters.assignee } : {}),
    ...(filters.open_only ? { open_only: true } : {}),
    ...(filters.stale_only ? { stale_only: true } : {}),
    ...(filters.created_after ? { created_after: filters.created_after } : {}),
    ...(filters.created_before ? { created_before: filters.created_before } : {}),
  };

  const { data: ticketsData, isLoading: ticketsLoading } = useQuery({
    queryKey: ["triage-tickets", queryParams],
    queryFn: () => api.getTickets(queryParams),
  });
  const tickets = ticketsData?.tickets ?? [];

  useEffect(() => {
    if (!ticketKey) {
      setOpenTicket(null);
      return;
    }
    const matchingTicket = tickets.find((ticket) => ticket.key === ticketKey);
    if (matchingTicket) {
      setOpenTicket(matchingTicket);
      return;
    }
    setOpenTicket((current) => (current?.key === ticketKey ? current : null));
  }, [ticketKey, tickets]);

  // Existing suggestions
  const { data: existingSuggestions } = useQuery({
    queryKey: ["triage-suggestions"],
    queryFn: () => api.getTriageSuggestions(),
  });
  const suggestionsMap = useMemo(() => {
    const map: Record<string, TriageResult> = {};
    for (const s of existingSuggestions ?? []) {
      map[s.key] = s;
    }
    return map;
  }, [existingSuggestions]);

  // Selection
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());

  // Analysis results (local state, merged with suggestions from server)
  const [localResults, setLocalResults] = useState<Record<string, TriageResult>>({});
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState("");

  // Dismissing state per ticket
  const [dismissingKey, setDismissingKey] = useState<string | null>(null);

  // Hide tickets with no suggested changes
  const [hideNoChanges, setHideNoChanges] = useState(false);

  // Re-analysis confirmation dialog
  const [confirmReeval, setConfirmReeval] = useState<{
    alreadyAnalyzed: string[];
    newKeys: string[];
  } | null>(null);

  // Merge existing suggestions + local results
  const allResults = useMemo(() => {
    const merged = { ...suggestionsMap, ...localResults };
    return merged;
  }, [suggestionsMap, localResults]);

  // Tickets with results (for the review panel)
  const reviewResults = useMemo(() => {
    let results = Object.values(allResults).filter((r) => !r.error);
    if (hideNoChanges) {
      results = results.filter((r) => r.suggestions.length > 0);
    }
    return results;
  }, [allResults, hideNoChanges]);

  // Toggle selection
  function toggleKey(key: string) {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  // Select all / none
  function toggleAll() {
    if (selectedKeys.size === tickets.length) {
      setSelectedKeys(new Set());
    } else {
      setSelectedKeys(new Set(tickets.map((t) => t.key)));
    }
  }

  // Core analysis call — sends keys to the API with optional force flag
  const runAnalysis = useCallback(
    async (keys: string[], force: boolean) => {
      setAnalyzing(true);
      setAnalyzeError("");
      try {
        const results = await api.analyzeTickets(keys, selectedModel, force);
        const newResults: Record<string, TriageResult> = {};
        for (const r of results) {
          newResults[r.key] = r;
        }
        setLocalResults((prev) => ({ ...prev, ...newResults }));
        queryClient.invalidateQueries({ queryKey: ["triage-suggestions"] });
      } catch (err) {
        logClientError("Failed to analyze tickets", err, {
          keys,
          force,
          selectedModel,
        });
        setAnalyzeError(
          err instanceof Error ? err.message : "Analysis failed"
        );
      } finally {
        setAnalyzing(false);
      }
    },
    [selectedModel, queryClient]
  );

  // Analyze selected — checks for previously-analyzed tickets first
  function handleAnalyze() {
    if (selectedKeys.size === 0 || !selectedModel) return;
    const keys = Array.from(selectedKeys);
    const cached = keys.filter(
      (k) => k in allResults && !allResults[k].error
    );
    const fresh = keys.filter(
      (k) => !(k in allResults && !allResults[k].error)
    );

    if (cached.length > 0) {
      setConfirmReeval({ alreadyAnalyzed: cached, newKeys: fresh });
    } else {
      runAnalysis(keys, false);
    }
  }

  // Confirmation dialog handlers
  function handleConfirmAll() {
    if (!confirmReeval) return;
    const allKeys = [
      ...confirmReeval.newKeys,
      ...confirmReeval.alreadyAnalyzed,
    ];
    setConfirmReeval(null);
    runAnalysis(allKeys, true);
  }

  function handleConfirmNewOnly() {
    if (!confirmReeval) return;
    setConfirmReeval(null);
    if (confirmReeval.newKeys.length > 0) {
      runAnalysis(confirmReeval.newKeys, false);
    }
  }

  function handleConfirmCancel() {
    setConfirmReeval(null);
  }

  // Per-field accept: after the API call succeeds, remove that field from local state
  function handleFieldAccepted(key: string, field: string) {
    setLocalResults((prev) => {
      const result = prev[key];
      if (!result) return prev;
      const remaining = result.suggestions.filter((s) => s.field !== field);
      if (remaining.length === 0) {
        const next = { ...prev };
        delete next[key];
        return next;
      }
      return { ...prev, [key]: { ...result, suggestions: remaining } };
    });
    queryClient.invalidateQueries({ queryKey: ["triage-suggestions"] });
    queryClient.invalidateQueries({ queryKey: ["triage-tickets"] });
  }

  // Per-field decline: remove that field from local state only (no API call)
  function handleFieldDeclined(key: string, field: string) {
    setLocalResults((prev) => {
      const result = prev[key];
      if (!result) return prev;
      const remaining = result.suggestions.filter((s) => s.field !== field);
      if (remaining.length === 0) {
        const next = { ...prev };
        delete next[key];
        return next;
      }
      return { ...prev, [key]: { ...result, suggestions: remaining } };
    });
  }

  // Incremental rendering for ticket table
  const TICKET_PAGE = 100;
  const [visibleTicketCount, setVisibleTicketCount] = useState(TICKET_PAGE);
  const ticketSentinelRef = useRef<HTMLDivElement>(null);

  // Reset visible count when tickets change
  useEffect(() => {
    setVisibleTicketCount(TICKET_PAGE);
  }, [tickets.length]);

  const loadMoreTickets = useCallback(() => {
    setVisibleTicketCount((prev) => Math.min(prev + TICKET_PAGE, tickets.length));
  }, [tickets.length]);

  useEffect(() => {
    const el = ticketSentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) loadMoreTickets(); },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loadMoreTickets, visibleTicketCount]);

  const visibleTickets = tickets.slice(0, visibleTicketCount);
  const hasMoreTickets = visibleTicketCount < tickets.length;

  // Incremental rendering for review panel
  const REVIEW_PAGE = 50;
  const [visibleReviewCount, setVisibleReviewCount] = useState(REVIEW_PAGE);
  const reviewSentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setVisibleReviewCount(REVIEW_PAGE);
  }, [reviewResults.length]);

  const loadMoreReviews = useCallback(() => {
    setVisibleReviewCount((prev) => Math.min(prev + REVIEW_PAGE, reviewResults.length));
  }, [reviewResults.length]);

  useEffect(() => {
    const el = reviewSentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) loadMoreReviews(); },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loadMoreReviews, visibleReviewCount]);

  const visibleReviews = reviewResults.slice(0, visibleReviewCount);
  const hasMoreReviews = visibleReviewCount < reviewResults.length;

  // Dismiss all suggestions for a ticket
  async function handleDismissAll(key: string) {
    setDismissingKey(key);
    try {
      await api.dismissTriageSuggestion(key);
      setLocalResults((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      queryClient.invalidateQueries({ queryKey: ["triage-suggestions"] });
    } catch (err) {
      logClientError("Failed to dismiss triage suggestions", err, { key });
    } finally {
      setDismissingKey(null);
    }
  }

  const rememberOpenTicket = useCallback(
    (key: string) => {
      const matchingTicket = tickets.find((ticket) => ticket.key === key) ?? null;
      setOpenTicket(matchingTicket);
    },
    [tickets],
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">AI Triage</h1>
          <p className="mt-1 text-sm text-gray-500">
            Select tickets, pick an AI model, and get triage suggestions.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Model selector */}
          <div>
            <label
              htmlFor="model-select"
              className="block text-xs font-medium text-gray-500"
            >
              AI Model
            </label>
            <select
              id="model-select"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              disabled={modelsLoading}
              className="mt-0.5 h-9 rounded-md border border-gray-300 bg-white px-3 pr-8 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
            >
              {modelsLoading && (
                <option value="">Loading models…</option>
              )}
              {!modelsLoading && models && models.length === 0 && (
                <option value="" disabled>
                  No models available — add API key
                </option>
              )}
              {(models ?? []).map((m: AIModel) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.provider})
                </option>
              ))}
            </select>
          </div>

          {/* Analyze button */}
          <button
            type="button"
            disabled={selectedKeys.size === 0 || !selectedModel || analyzing}
            onClick={handleAnalyze}
            className="mt-4 h-9 rounded-md bg-indigo-600 px-4 text-sm font-medium text-white shadow-sm transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {analyzing
              ? `Analyzing ${selectedKeys.size}…`
              : `Analyze ${selectedKeys.size || ""} Selected`}
          </button>
        </div>
      </div>

      {/* Error */}
      {analyzeError && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {analyzeError}
        </div>
      )}

      {/* Re-analysis confirmation dialog */}
      {confirmReeval && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-4">
          <h3 className="text-sm font-semibold text-amber-800">
            Re-analyze previously triaged tickets?
          </h3>
          <p className="mt-1 text-sm text-amber-700">
            {confirmReeval.alreadyAnalyzed.length} of your selected tickets
            already have AI suggestions:{" "}
            <span className="font-medium">
              {confirmReeval.alreadyAnalyzed.join(", ")}
            </span>
          </p>
          {confirmReeval.newKeys.length > 0 && (
            <p className="mt-1 text-sm text-amber-700">
              {confirmReeval.newKeys.length} ticket(s) have not been analyzed
              yet.
            </p>
          )}
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={handleConfirmAll}
              className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-amber-700"
            >
              Re-analyze All ({confirmReeval.alreadyAnalyzed.length + confirmReeval.newKeys.length})
            </button>
            {confirmReeval.newKeys.length > 0 && (
              <button
                type="button"
                onClick={handleConfirmNewOnly}
                className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50"
              >
                Only Analyze New ({confirmReeval.newKeys.length})
              </button>
            )}
            <button
              type="button"
              onClick={handleConfirmCancel}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Filters */}
      <TicketFilters filters={filters} onFilterChange={handleFilterChange} />

      {/* Two-column layout: tickets left, review right */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {/* Ticket selection panel */}
        <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
            <h2 className="text-sm font-semibold text-gray-700">
              Tickets{" "}
              <span className="font-normal text-gray-400">
                ({tickets.length})
              </span>
            </h2>
          </div>

          <div className="max-h-[60vh] overflow-y-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-2">
                    <input
                      type="checkbox"
                      checked={
                        tickets.length > 0 &&
                        selectedKeys.size === tickets.length
                      }
                      onChange={toggleAll}
                      className="rounded border-gray-300"
                    />
                  </th>
                  <th className="px-2 py-2">Key</th>
                  <th className="px-2 py-2">Summary</th>
                  <th className="px-2 py-2">Priority</th>
                  <th className="px-2 py-2">Request Type</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Assignee</th>
                  <th className="px-2 py-2 text-center">AI</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {ticketsLoading && (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-gray-400">
                      Loading tickets…
                    </td>
                  </tr>
                )}
                {!ticketsLoading && tickets.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-gray-400">
                      No open tickets found.
                    </td>
                  </tr>
                )}
                {visibleTickets.map((t: TicketRow) => (
                  <tr
                    key={t.key}
                    className={`cursor-pointer transition-colors hover:bg-gray-50 ${
                      selectedKeys.has(t.key) ? "bg-blue-50" : ""
                    }`}
                    onClick={() => toggleKey(t.key)}
                  >
                    <td className="px-4 py-2">
                      <input
                        type="checkbox"
                        checked={selectedKeys.has(t.key)}
                        onChange={() => toggleKey(t.key)}
                        onClick={(e) => e.stopPropagation()}
                        className="rounded border-gray-300"
                      />
                    </td>
                    <td className="whitespace-nowrap px-2 py-2 font-medium text-blue-600">
                      <Link
                        to={buildTicketHref(t.key)}
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpenTicket(t);
                        }}
                        className="hover:underline"
                      >
                        {t.key}
                      </Link>
                    </td>
                    <td className="max-w-[200px] truncate px-2 py-2 text-gray-700">
                      {t.summary}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2 text-gray-600">
                      {t.priority}
                    </td>
                    <td className="max-w-[140px] truncate px-2 py-2 text-gray-600">
                      {t.request_type || "—"}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2 text-gray-600">
                      {t.status}
                    </td>
                    <td className="max-w-[120px] truncate px-2 py-2 text-gray-600">
                      {t.assignee || "Unassigned"}
                    </td>
                    <td className="px-2 py-2 text-center">
                      {allResults[t.key] && !allResults[t.key].error && (
                        <span className="inline-block h-2 w-2 rounded-full bg-green-500" title="AI suggestion available" />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {hasMoreTickets && (
              <div ref={ticketSentinelRef} className="px-4 py-2 text-center text-xs text-gray-400">
                Showing {visibleTicketCount} of {tickets.length} — scroll for more
              </div>
            )}
          </div>
        </div>

        {/* Review panel */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700">
              Triage Suggestions{" "}
              <span className="font-normal text-gray-400">
                ({reviewResults.length})
              </span>
            </h2>
            <label className="flex items-center gap-1.5 text-xs text-gray-500">
              <input
                type="checkbox"
                checked={hideNoChanges}
                onChange={(e) => setHideNoChanges(e.target.checked)}
                className="rounded border-gray-300"
              />
              Hide no-change results
            </label>
          </div>

          {reviewResults.length === 0 && (
            <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-12 text-center text-sm text-gray-400">
              Select tickets and click <strong>Analyze</strong> to generate AI
              triage suggestions.
            </div>
          )}

          <div className="max-h-[60vh] space-y-3 overflow-y-auto">
            {visibleReviews.map((r) => (
              <TriageReviewPanel
                key={r.key}
                result={r}
                ticketHrefBuilder={buildTicketHref}
                onOpenTicket={rememberOpenTicket}
                onFieldAccepted={handleFieldAccepted}
                onFieldDeclined={handleFieldDeclined}
                onDismissAll={handleDismissAll}
                dismissing={dismissingKey === r.key}
              />
            ))}
            {hasMoreReviews && (
              <div ref={reviewSentinelRef} className="py-2 text-center text-xs text-gray-400">
                Showing {visibleReviewCount} of {reviewResults.length} — scroll for more
              </div>
            )}
          </div>
        </div>
      </div>

      <TicketWorkbenchDrawer
        ticketKey={ticketKey}
        initialTicket={openTicket}
        onClose={closeTicket}
      />
    </div>
  );
}
