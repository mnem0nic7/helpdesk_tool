import { useState, useEffect, useMemo, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type {
  TicketRow,
  TicketQueryParams,
  AIModel,
  TriageResult,
  TriageSuggestion,
} from "../lib/api.ts";

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
// Suggestion card
// ---------------------------------------------------------------------------

function SuggestionCard({
  suggestion,
  accepted,
  onToggle,
}: {
  suggestion: TriageSuggestion;
  accepted: boolean;
  onToggle: () => void;
}) {
  const fieldLabels: Record<string, string> = {
    priority: "Priority",
    status: "Status",
    assignee: "Assignee",
    comment: "Comment",
    request_type: "Request Type",
  };

  return (
    <div
      className={`rounded-lg border p-3 transition-colors ${
        accepted
          ? "border-blue-300 bg-blue-50"
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
        </div>
        <button
          type="button"
          onClick={onToggle}
          className={`shrink-0 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
            accepted
              ? "border-blue-500 bg-blue-600 text-white hover:bg-blue-700"
              : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
          }`}
        >
          {accepted ? "Accepted" : "Accept"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ticket triage review panel
// ---------------------------------------------------------------------------

function TriageReviewPanel({
  result,
  onApply,
  applying,
}: {
  result: TriageResult;
  onApply: (key: string, fields: string[]) => void;
  applying: boolean;
}) {
  const [acceptedFields, setAcceptedFields] = useState<Set<string>>(
    () => new Set(result.suggestions.map((s) => s.field))
  );

  function toggleField(field: string) {
    setAcceptedFields((prev) => {
      const next = new Set(prev);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  }

  if (result.suggestions.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
        No changes suggested for <strong>{result.key}</strong> — the ticket
        looks well-triaged.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
        <div>
          <span className="font-semibold text-gray-900">{result.key}</span>
          <span className="ml-2 text-xs text-gray-400">
            via {result.model_used}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">
            {acceptedFields.size}/{result.suggestions.length} accepted
          </span>
          <button
            type="button"
            disabled={acceptedFields.size === 0 || applying}
            onClick={() => onApply(result.key, Array.from(acceptedFields))}
            className="rounded-md bg-green-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {applying ? "Applying…" : "Apply Accepted"}
          </button>
        </div>
      </div>
      <div className="space-y-2 p-4">
        {result.suggestions.map((s) => (
          <SuggestionCard
            key={s.field}
            suggestion={s}
            accepted={acceptedFields.has(s.field)}
            onToggle={() => toggleField(s.field)}
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

  // Model selection
  const { data: models } = useQuery({
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

  // Ticket list
  const queryParams: TicketQueryParams = { open_only: true };
  const { data: ticketsData, isLoading: ticketsLoading } = useQuery({
    queryKey: ["triage-tickets", queryParams],
    queryFn: () => api.getTickets(queryParams),
  });
  const tickets = ticketsData?.tickets ?? [];

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

  // Applying state per ticket
  const [applyingKey, setApplyingKey] = useState<string | null>(null);

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
    return Object.values(allResults).filter((r) => !r.error);
  }, [allResults]);

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

  // Apply suggestions
  async function handleApply(key: string, fields: string[]) {
    setApplyingKey(key);
    try {
      await api.applyTriageSuggestion(key, fields);
      // Remove from local state
      setLocalResults((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      // Refresh
      queryClient.invalidateQueries({ queryKey: ["triage-suggestions"] });
      queryClient.invalidateQueries({ queryKey: ["triage-tickets"] });
      api.refreshCacheIncremental().then(() => {
        queryClient.invalidateQueries({ queryKey: ["triage-tickets"] });
      });
    } catch {
      // Error handling is visible through the review panel
    } finally {
      setApplyingKey(null);
    }
  }

  // Search filter for tickets
  const [search, setSearch] = useState("");
  const filteredTickets = useMemo(() => {
    if (!search) return tickets;
    const q = search.toLowerCase();
    return tickets.filter(
      (t) =>
        t.key.toLowerCase().includes(q) ||
        t.summary.toLowerCase().includes(q) ||
        t.assignee.toLowerCase().includes(q)
    );
  }, [tickets, search]);

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
              className="mt-0.5 h-9 rounded-md border border-gray-300 bg-white px-3 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {(models ?? []).map((m: AIModel) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.provider})
                </option>
              ))}
              {(!models || models.length === 0) && (
                <option value="" disabled>
                  No models available — add API key
                </option>
              )}
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

      {/* Two-column layout: tickets left, review right */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {/* Ticket selection panel */}
        <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
            <h2 className="text-sm font-semibold text-gray-700">
              Open Tickets{" "}
              <span className="font-normal text-gray-400">
                ({filteredTickets.length})
              </span>
            </h2>
            <input
              type="text"
              placeholder="Search tickets…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 w-48 rounded-md border border-gray-300 px-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div className="max-h-[60vh] overflow-y-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-2">
                    <input
                      type="checkbox"
                      checked={
                        filteredTickets.length > 0 &&
                        selectedKeys.size === filteredTickets.length
                      }
                      onChange={toggleAll}
                      className="rounded border-gray-300"
                    />
                  </th>
                  <th className="px-2 py-2">Key</th>
                  <th className="px-2 py-2">Summary</th>
                  <th className="px-2 py-2">Priority</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Assignee</th>
                  <th className="px-2 py-2 text-center">AI</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {ticketsLoading && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-gray-400">
                      Loading tickets…
                    </td>
                  </tr>
                )}
                {!ticketsLoading && filteredTickets.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-gray-400">
                      No open tickets found.
                    </td>
                  </tr>
                )}
                {filteredTickets.map((t: TicketRow) => (
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
                      {t.key}
                    </td>
                    <td className="max-w-[200px] truncate px-2 py-2 text-gray-700">
                      {t.summary}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2 text-gray-600">
                      {t.priority}
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
          </div>
        </div>

        {/* Review panel */}
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-700">
            Triage Suggestions{" "}
            <span className="font-normal text-gray-400">
              ({reviewResults.length})
            </span>
          </h2>

          {reviewResults.length === 0 && (
            <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-12 text-center text-sm text-gray-400">
              Select tickets and click <strong>Analyze</strong> to generate AI
              triage suggestions.
            </div>
          )}

          <div className="max-h-[60vh] space-y-3 overflow-y-auto">
            {reviewResults.map((r) => (
              <TriageReviewPanel
                key={r.key}
                result={r}
                onApply={handleApply}
                applying={applyingKey === r.key}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
