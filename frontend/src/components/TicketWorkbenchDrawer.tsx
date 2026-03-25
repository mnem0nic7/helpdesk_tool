import { useDeferredValue, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import { getSiteBranding } from "../lib/siteContext.ts";
import JiraWriteIdentityNotice from "./JiraWriteIdentityNotice.tsx";
import type {
  Assignee,
  PriorityOption,
  TicketComment,
  TicketAttachment,
  RequestTypeOption,
  TicketDetail,
  TicketRow,
  Transition,
} from "../lib/api.ts";

interface TicketWorkbenchDrawerProps {
  ticketKey: string | null;
  initialTicket?: TicketRow | null;
  onClose: () => void;
}

const DEFAULT_DRAWER_WIDTH = 768;
const MIN_DRAWER_WIDTH = 640;
const VIEWPORT_MARGIN = 32;

function clampDrawerWidth(width: number): number {
  if (typeof window === "undefined") return DEFAULT_DRAWER_WIDTH;
  const maxWidth = Math.max(360, window.innerWidth - VIEWPORT_MARGIN);
  const minWidth = Math.min(MIN_DRAWER_WIDTH, maxWidth);
  return Math.min(Math.max(width, minWidth), maxWidth);
}

function getExpandedDrawerWidth(): number {
  if (typeof window === "undefined") return DEFAULT_DRAWER_WIDTH;
  return clampDrawerWidth(window.innerWidth - VIEWPORT_MARGIN);
}

function formatDateTime(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

function formatBytes(size: number): string {
  if (!size) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatAttachmentType(attachment: TicketAttachment): string {
  const extension = attachment.extension.replace(/^\./, "").toUpperCase();
  if (attachment.preview_kind === "office") {
    return extension || "Office Document";
  }
  if (attachment.preview_kind === "pdf") {
    return "PDF";
  }
  if (attachment.preview_kind === "image") {
    return extension ? `${extension} Image` : "Image";
  }
  if (attachment.preview_kind === "text") {
    return extension || "Text";
  }
  return attachment.mime_type || extension || "Unknown type";
}

function previewButtonLabel(attachment: TicketAttachment): string {
  if (attachment.preview_kind === "office") {
    return "Preview Document";
  }
  return "Preview";
}

function isIframePreviewKind(kind: TicketAttachment["preview_kind"]): boolean {
  return kind === "pdf" || kind === "office";
}

function chipClass(color: "slate" | "blue" | "amber" | "green") {
  const classes = {
    slate: "bg-slate-100 text-slate-700",
    blue: "bg-blue-100 text-blue-700",
    amber: "bg-amber-100 text-amber-700",
    green: "bg-green-100 text-green-700",
  };
  return `inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${classes[color]}`;
}

function sortCommentsByCreated(comments: TicketComment[]): TicketComment[] {
  return [...comments].sort((a, b) => {
    const aTime = new Date(a.created).getTime();
    const bTime = new Date(b.created).getTime();
    return bTime - aTime;
  });
}

function getTransitionLabel(transition: Transition): string {
  return (transition.to_status || transition.name || "").trim();
}

function normalizeStatusLabel(label: string): string {
  return label.trim().toLowerCase();
}

function parseComponentInput(value: string): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of value.split(",")) {
    const trimmed = item.trim();
    const key = trimmed.toLowerCase();
    if (!trimmed || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(trimmed);
  }
  return result;
}

function normalizeRequestTypeName(name: string): string {
  return name.trim().toLowerCase();
}

function normalizeSummaryInput(value: string): string {
  return value.replace(/\r?\n+/g, " ");
}

function formatScore(score: number): string {
  return `${score.toFixed(1)}/5`;
}

export default function TicketWorkbenchDrawer({
  ticketKey,
  initialTicket,
  onClose,
}: TicketWorkbenchDrawerProps) {
  const queryClient = useQueryClient();
  const [summary, setSummary] = useState("");
  const [description, setDescription] = useState("");
  const [drawerWidth, setDrawerWidth] = useState(() => clampDrawerWidth(DEFAULT_DRAWER_WIDTH));
  const [isResizing, setIsResizing] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [selectedPriority, setSelectedPriority] = useState("");
  const [selectedAssignee, setSelectedAssignee] = useState("");
  const [reporterSearch, setReporterSearch] = useState("");
  const [selectedReporterAccountId, setSelectedReporterAccountId] = useState("");
  const [selectedRequestTypeId, setSelectedRequestTypeId] = useState("");
  const [selectedTransitionId, setSelectedTransitionId] = useState("");
  const [applicationInput, setApplicationInput] = useState("");
  const [workCategoryInput, setWorkCategoryInput] = useState("");
  const [comment, setComment] = useState("");
  const [commentAudience, setCommentAudience] = useState<"internal" | "customer">("internal");
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [previewAttachment, setPreviewAttachment] = useState<TicketAttachment | null>(null);
  const [previewObjectUrl, setPreviewObjectUrl] = useState("");
  const [previewText, setPreviewText] = useState("");
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  const summaryInputRef = useRef<HTMLTextAreaElement | null>(null);

  const { data: detail, isLoading } = useQuery({
    queryKey: ["ticket-detail", ticketKey],
    queryFn: () => api.getTicket(ticketKey ?? ""),
    enabled: !!ticketKey,
  });

  const { data: assignees = [] } = useQuery({
    queryKey: ["assignees"],
    queryFn: () => api.getAssignees(),
    staleTime: 5 * 60 * 1000,
    enabled: !!ticketKey,
  });

  const deferredReporterSearch = useDeferredValue(reporterSearch.trim());
  const currentReporterName = (detail?.ticket.reporter ?? initialTicket?.reporter ?? "").trim();
  const showReporterMatches =
    deferredReporterSearch.length >= 2 &&
    deferredReporterSearch.toLowerCase() !== currentReporterName.toLowerCase();

  const { data: reporterOptions = [], isFetching: isSearchingReporters } = useQuery({
    queryKey: ["user-search", deferredReporterSearch],
    queryFn: () => api.searchUsers(deferredReporterSearch),
    staleTime: 30 * 1000,
    enabled: !!ticketKey && showReporterMatches,
  });

  const { data: priorities = [] } = useQuery({
    queryKey: ["priorities"],
    queryFn: () => api.getPriorities(),
    staleTime: 5 * 60 * 1000,
    enabled: !!ticketKey,
  });

  const { data: requestTypes = [] } = useQuery({
    queryKey: ["request-types"],
    queryFn: () => api.getRequestTypes(),
    staleTime: 5 * 60 * 1000,
    enabled: !!ticketKey,
  });

  const { data: transitions = [] } = useQuery({
    queryKey: ["ticket-transitions", ticketKey],
    queryFn: () => api.getTransitions(ticketKey ?? ""),
    enabled: !!ticketKey,
  });

  const { data: filterOptions } = useQuery({
    queryKey: ["filter-options"],
    queryFn: () => api.getFilterOptions(),
    staleTime: 5 * 60 * 1000,
    enabled: !!ticketKey,
  });

  const { data: technicianScores = [], isLoading: isLoadingTechnicianScores } = useQuery({
    queryKey: ["technician-scores", ticketKey],
    queryFn: () => api.getTechnicianScores({ key: ticketKey ?? "" }),
    enabled: !!ticketKey,
    staleTime: 5 * 60 * 1000,
  });
  const { data: me } = useQuery({
    queryKey: ["me", "ticket-jira-write"],
    queryFn: () => api.getMe(),
    staleTime: 60_000,
    enabled: !!ticketKey,
  });

  useEffect(() => {
    if (!detail) return;
    setSummary(normalizeSummaryInput(detail.ticket.summary));
    setDescription(detail.description);
    setSelectedPriority(detail.ticket.priority);
    setSelectedAssignee(detail.ticket.assignee_account_id ?? "");
    setReporterSearch(detail.ticket.reporter ?? "");
    setSelectedReporterAccountId(detail.ticket.reporter_account_id ?? "");
    setComment("");
    setCommentAudience("internal");
    setSelectedTransitionId("");
    setApplicationInput(detail.ticket.components.join(", "));
    setWorkCategoryInput(detail.work_category ?? "");
    setIsHistoryOpen(false);
    setPreviewAttachment(null);
  }, [detail]);

  useEffect(() => {
    if (!previewAttachment) {
      setPreviewObjectUrl((current) => {
        if (current) {
          URL.revokeObjectURL(current);
        }
        return "";
      });
      setPreviewText("");
      setPreviewError(null);
      setIsPreviewLoading(false);
      return;
    }

    let objectUrl = "";
    let cancelled = false;

    setPreviewText("");
    setPreviewError(null);
    setIsPreviewLoading(true);

    const loadPreview = async () => {
      try {
        if (!previewAttachment.preview_available || !previewAttachment.preview_url) {
          throw new Error("Preview is not available for this attachment.");
        }
        if (isIframePreviewKind(previewAttachment.preview_kind)) {
          return;
        }
        if (previewAttachment.preview_kind === "text") {
          const text = await api.fetchAttachmentPreviewText(previewAttachment.preview_url);
          if (!cancelled) {
            setPreviewText(text);
          }
          return;
        }
        const blob = await api.fetchAttachmentPreviewBlob(previewAttachment.preview_url);
        objectUrl = URL.createObjectURL(blob);
        if (!cancelled) {
          setPreviewObjectUrl(objectUrl);
        }
      } catch (error) {
        if (!cancelled) {
          setPreviewError(error instanceof Error ? error.message : "Unable to load attachment preview.");
        }
      } finally {
        if (!cancelled) {
          setIsPreviewLoading(false);
        }
      }
    };

    setPreviewObjectUrl((current) => {
      if (current) {
        URL.revokeObjectURL(current);
      }
      return "";
    });
    loadPreview();

    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [previewAttachment]);

  useEffect(() => {
    const textarea = summaryInputRef.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [drawerWidth, summary]);

  const effectiveRequestTypeName =
    detail?.ticket.request_type?.trim() ||
    detail?.request_type?.trim() ||
    initialTicket?.request_type?.trim() ||
    "";
  const effectiveRequestTypeId =
    detail?.ticket.request_type_id?.trim() ||
    initialTicket?.request_type_id?.trim() ||
    "";
  const matchedCurrentRequestType = useMemo(() => {
    if (!requestTypes.length) return null;
    if (effectiveRequestTypeId) {
      const exactIdMatch = requestTypes.find((option) => option.id === effectiveRequestTypeId);
      if (exactIdMatch) {
        return exactIdMatch;
      }
    }
    if (!effectiveRequestTypeName) return null;
    const normalizedCurrentName = normalizeRequestTypeName(effectiveRequestTypeName);
    return (
      requestTypes.find((option) => normalizeRequestTypeName(option.name) === normalizedCurrentName) ?? null
    );
  }, [effectiveRequestTypeId, effectiveRequestTypeName, requestTypes]);
  const fallbackRequestTypeOption = useMemo(() => {
    if (!effectiveRequestTypeName || matchedCurrentRequestType) return null;
    return {
      id: effectiveRequestTypeId || `__current__:${effectiveRequestTypeName}`,
      name: effectiveRequestTypeName,
      description: "",
    };
  }, [effectiveRequestTypeId, effectiveRequestTypeName, matchedCurrentRequestType]);

  useEffect(() => {
    if (!ticketKey) return;
    setSelectedRequestTypeId(
      matchedCurrentRequestType?.id ??
      fallbackRequestTypeOption?.id ??
      "",
    );
  }, [fallbackRequestTypeOption, matchedCurrentRequestType, ticketKey]);

  useEffect(() => {
    if (!showReporterMatches) return;
    const normalized = reporterSearch.trim().toLowerCase();
    const exactMatches = reporterOptions.filter((option) => {
      const displayName = option.display_name.trim().toLowerCase();
      const email = (option.email_address ?? "").trim().toLowerCase();
      return displayName === normalized || (!!email && email === normalized);
    });
    if (exactMatches.length === 1) {
      setSelectedReporterAccountId(exactMatches[0].account_id);
    }
  }, [reporterOptions, reporterSearch, showReporterMatches]);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handleResize = () => {
      setDrawerWidth((current) => (isExpanded ? getExpandedDrawerWidth() : clampDrawerWidth(current)));
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [isExpanded]);

  useEffect(() => {
    if (!isResizing) return undefined;

    const previousUserSelect = document.body.style.userSelect;
    const previousCursor = document.body.style.cursor;
    const updateWidth = (clientX: number) => {
      setDrawerWidth(clampDrawerWidth(window.innerWidth - clientX));
    };

    const handlePointerMove = (event: PointerEvent) => {
      event.preventDefault();
      updateWidth(event.clientX);
    };

    const handleMouseMove = (event: MouseEvent) => {
      event.preventDefault();
      updateWidth(event.clientX);
    };

    const stopResizing = () => {
      setIsResizing(false);
    };

    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("pointerup", stopResizing);
    window.addEventListener("mouseup", stopResizing);

    return () => {
      document.body.style.userSelect = previousUserSelect;
      document.body.style.cursor = previousCursor;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("pointerup", stopResizing);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, [isResizing]);

  useEffect(() => {
    if (!isHistoryOpen) return undefined;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsHistoryOpen(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isHistoryOpen]);

  function handleResizeStart(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setIsExpanded(false);
    setIsResizing(true);
  }

  function toggleExpanded() {
    setIsExpanded((current) => {
      const next = !current;
      setDrawerWidth(next ? getExpandedDrawerWidth() : clampDrawerWidth(DEFAULT_DRAWER_WIDTH));
      return next;
    });
  }

  function handleUpdated(next: TicketDetail, message: string) {
    queryClient.setQueryData(["ticket-detail", ticketKey], next);
    queryClient.invalidateQueries({ queryKey: ["tickets"] });
    queryClient.invalidateQueries({ queryKey: ["manage-tickets"] });
    queryClient.invalidateQueries({ queryKey: ["filter-options"] });
    setFeedback(message);
    setErrorText(null);
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!detail || !ticketKey) {
        throw new Error("Ticket detail not loaded");
      }
      const payload: Record<string, unknown> = {};
      const normalizedSummary = normalizeSummaryInput(summary).trim();
      if (normalizedSummary !== detail.ticket.summary) payload.summary = normalizedSummary;
      if (description !== detail.description) payload.description = description;
      if (selectedPriority !== detail.ticket.priority) payload.priority = selectedPriority;
      if ((selectedAssignee || "") !== (detail.ticket.assignee_account_id || "")) {
        payload.assignee_account_id = selectedAssignee || null;
      }
      const trimmedReporter = reporterSearch.trim();
      const currentReporterAccountId = detail.ticket.reporter_account_id ?? "";
      const reporterChanged =
        trimmedReporter !== (detail.ticket.reporter ?? "").trim() ||
        selectedReporterAccountId !== currentReporterAccountId;
      if (reporterChanged) {
        if (!trimmedReporter) {
          throw new Error("Reporter cannot be empty");
        }
        if (!selectedReporterAccountId) {
          throw new Error("Select a Jira user for the reporter before saving");
        }
        const selectedReporterOption = reporterOptions.find(
          (option) => option.account_id === selectedReporterAccountId,
        );
        payload.reporter_account_id = selectedReporterAccountId;
        payload.reporter_display_name = selectedReporterOption?.display_name ?? trimmedReporter;
      }
      const currentRequestTypeId =
        matchedCurrentRequestType?.id ??
        fallbackRequestTypeOption?.id ??
        "";
      if (
        selectedRequestTypeId &&
        !selectedRequestTypeId.startsWith("__current__:") &&
        selectedRequestTypeId !== currentRequestTypeId
      ) {
        payload.request_type_id = selectedRequestTypeId;
      }
      const nextComponents = parseComponentInput(applicationInput);
      const currentComponents = (detail.ticket.components ?? []).map((component) => component.trim()).filter(Boolean);
      if (JSON.stringify(nextComponents) !== JSON.stringify(currentComponents)) {
        payload.components = nextComponents;
      }
      const trimmedWorkCategory = workCategoryInput.trim();
      const currentWorkCategory = (detail.work_category ?? "").trim();
      if (trimmedWorkCategory !== currentWorkCategory) {
        payload.work_category = trimmedWorkCategory;
      }
      if (Object.keys(payload).length === 0) {
        throw new Error("No changes to save");
      }
      return api.updateTicket(ticketKey, payload);
    },
    onSuccess: (next) => handleUpdated(next, "Ticket details updated"),
    onError: (error) => {
      setErrorText(error instanceof Error ? error.message : "Failed to update ticket");
      setFeedback(null);
    },
  });

  const syncReporterMutation = useMutation({
    mutationFn: () => {
      if (!ticketKey) {
        throw new Error("No ticket selected");
      }
      return api.syncTicketReporter(ticketKey);
    },
    onSuccess: (result) => handleUpdated(result.detail, result.message),
    onError: (error) => {
      setErrorText(error instanceof Error ? error.message : "Failed to update reporter");
      setFeedback(null);
    },
  });

  const transitionMutation = useMutation({
    mutationFn: () => {
      if (!ticketKey || !selectedTransitionId) {
        throw new Error("Choose a transition first");
      }
      return api.transitionTicket(ticketKey, selectedTransitionId);
    },
    onSuccess: (next) => handleUpdated(next, "Status updated"),
    onError: (error) => {
      setErrorText(error instanceof Error ? error.message : "Failed to transition ticket");
      setFeedback(null);
    },
  });

  const commentMutation = useMutation({
    mutationFn: () => {
      if (!ticketKey || !comment.trim()) {
        throw new Error("Comment cannot be empty");
      }
      return api.addTicketComment(ticketKey, comment.trim(), commentAudience === "customer");
    },
    onSuccess: (next) =>
      handleUpdated(next, commentAudience === "customer" ? "Reply sent to customer" : "Internal note added"),
    onError: (error) => {
      setErrorText(error instanceof Error ? error.message : "Failed to add comment");
      setFeedback(null);
    },
  });

  const removeOasisDevMutation = useMutation({
    mutationFn: () => {
      if (!ticketKey) throw new Error("No ticket selected");
      return api.removeOasisDevLabel(ticketKey);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      onClose();
    },
    onError: (error) => {
      setErrorText(error instanceof Error ? error.message : "Failed to remove oasisdev label");
      setFeedback(null);
    },
  });

  if (!ticketKey) return null;

  const ticket = detail?.ticket ?? initialTicket;
  const sortedAssignees = [...assignees].sort((a: Assignee, b: Assignee) =>
    a.display_name.localeCompare(b.display_name)
  );
  const sortedReporterOptions = [...reporterOptions].sort((a: Assignee, b: Assignee) =>
    a.display_name.localeCompare(b.display_name)
  );
  const sortedRequestTypes = [...requestTypes].sort((a: RequestTypeOption, b: RequestTypeOption) =>
    a.name.localeCompare(b.name)
  );
  const visibleRequestTypes = fallbackRequestTypeOption
    ? [...sortedRequestTypes, fallbackRequestTypeOption].sort((a, b) => a.name.localeCompare(b.name))
    : sortedRequestTypes;
  const sortedPriorities = [...priorities].sort((a: PriorityOption, b: PriorityOption) =>
    a.name.localeCompare(b.name)
  );
  const componentOptions = filterOptions?.components ?? [];
  const workCategoryOptions = filterOptions?.work_categories ?? [];
  const currentStatusLabel = (ticket?.status ?? "").trim();
  const currentStatusKey = normalizeStatusLabel(currentStatusLabel);
  const seenTransitionLabels = new Set<string>();
  const displayTransitions = transitions.filter((transition) => {
    const label = getTransitionLabel(transition);
    const normalizedLabel = normalizeStatusLabel(label);
    if (!normalizedLabel || normalizedLabel === currentStatusKey || seenTransitionLabels.has(normalizedLabel)) {
      return false;
    }
    seenTransitionLabels.add(normalizedLabel);
    return true;
  });
  const actionContextItems = detail
    ? [
        { label: "Type", value: detail.ticket.issue_type || "—" },
        { label: "Reporter", value: detail.ticket.reporter || "—" },
        { label: "Created", value: formatDateTime(detail.ticket.created) },
        { label: "Updated", value: formatDateTime(detail.ticket.updated) },
        { label: "Resolved", value: formatDateTime(detail.ticket.resolved) },
        { label: "Category", value: detail.work_category || "—" },
      ]
    : [];
  const historyItems = detail ? sortCommentsByCreated(detail.comments) : [];
  const recentHistoryItems = historyItems.slice(0, 2);
  const customerReplyCount = historyItems.filter((item) => item.public).length;
  const internalNoteCount = historyItems.length - customerReplyCount;
  const technicianScore = technicianScores[0] ?? null;

  return (
    <div className="fixed inset-0 z-50 flex bg-slate-950/35" onClick={onClose}>
      <aside
        data-testid="ticket-workbench-drawer"
        className="relative ml-auto flex h-full max-w-full flex-col bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        style={{ width: `${drawerWidth}px` }}
      >
        <div
          role="separator"
          aria-label="Resize ticket drawer"
          aria-orientation="vertical"
          data-testid="ticket-workbench-resizer"
          className={[
            "absolute inset-y-0 left-0 z-10 w-3 -translate-x-1/2 cursor-col-resize touch-none",
            isResizing ? "bg-blue-200/70" : "bg-transparent hover:bg-slate-200/60",
          ].join(" ")}
          onPointerDown={handleResizeStart}
          onDoubleClick={() => {
            setIsExpanded(false);
            setDrawerWidth(clampDrawerWidth(DEFAULT_DRAWER_WIDTH));
          }}
        >
          <div className="absolute left-1/2 top-1/2 h-14 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-300" />
        </div>

        <div className="border-b border-slate-200 px-5 py-3">
          <div className="space-y-3">
            <div className="min-w-0">
              <div className="font-mono text-xs font-semibold uppercase tracking-[0.2em] text-blue-700">
                {ticket?.key ?? ticketKey}
              </div>
              <label className="sr-only" htmlFor="ticket-summary-input">
                Summary
              </label>
              <textarea
                ref={summaryInputRef}
                id="ticket-summary-input"
                rows={1}
                value={summary}
                onChange={(e) => setSummary(normalizeSummaryInput(e.target.value))}
                className="mt-1.5 block w-full resize-none overflow-hidden rounded-md border border-transparent bg-transparent px-0 py-1 text-xl font-semibold leading-tight text-slate-900 shadow-none focus:border-blue-200 focus:bg-white focus:px-3 focus:outline-none focus:ring-2 focus:ring-blue-100"
                placeholder={ticket?.summary || "Loading ticket..."}
              />
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              {getSiteBranding().scope === "oasisdev" &&
                detail?.ticket.labels.some((l) => l.toLowerCase().includes("oasisdev")) && (
                  <button
                    type="button"
                    disabled={removeOasisDevMutation.isPending}
                    onClick={() => removeOasisDevMutation.mutate()}
                    className="rounded-md border border-amber-400 bg-amber-50 px-3 py-1.5 text-sm font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-50"
                  >
                    {removeOasisDevMutation.isPending ? "Removing…" : "Not Oasis Dev"}
                  </button>
                )}
              {detail?.portal_url && (
                <a
                  href={detail.portal_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Portal
                </a>
              )}
              {detail?.jira_url && (
                <a
                  href={detail.jira_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-md border border-blue-300 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-100"
                >
                  Open in Jira
                </a>
              )}
              <button
                type="button"
                onClick={toggleExpanded}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                {isExpanded ? "Restore" : "Expand"}
              </button>
              <button
                type="button"
                onClick={onClose}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          {(isLoading || !detail) && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              Loading full ticket detail...
            </div>
          )}

          {feedback && (
            <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
              {feedback}
            </div>
          )}

          {errorText && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {errorText}
            </div>
          )}

          {detail && (
            <>
              <section className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
                    Ticket Actions
                  </h3>
                  <span className="text-xs text-slate-500">All changes write directly to Jira</span>
                </div>
                <JiraWriteIdentityNotice
                  jiraAuth={me?.jira_auth}
                  className="mt-3"
                />

                <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-12">
                  <label className="block xl:col-span-2">
                    <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Priority</span>
                    <select
                      value={selectedPriority}
                      onChange={(e) => setSelectedPriority(e.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    >
                      <option value="">Select priority</option>
                      {sortedPriorities.map((priority) => (
                        <option key={priority.id} value={priority.name}>
                          {priority.name}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="block xl:col-span-2">
                    <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Assignee</span>
                    <select
                      value={selectedAssignee}
                      onChange={(e) => setSelectedAssignee(e.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    >
                      <option value="">Unassigned</option>
                      {sortedAssignees.map((assignee) => (
                        <option key={assignee.account_id} value={assignee.account_id}>
                          {assignee.display_name}
                        </option>
                      ))}
                    </select>
                  </label>

                  <div className="block md:col-span-2 xl:col-span-4">
                    <label
                      htmlFor="ticket-reporter-input"
                      className="text-xs font-medium uppercase tracking-wide text-slate-500"
                    >
                      Reporter
                    </label>
                    <div className="mt-1 flex flex-col gap-2 xl:flex-row xl:items-start">
                      <input
                        id="ticket-reporter-input"
                        aria-label="Reporter"
                        type="text"
                        value={reporterSearch}
                        onChange={(e) => {
                          const nextValue = e.target.value;
                          setReporterSearch(nextValue);
                          const normalized = nextValue.trim().toLowerCase();
                          if (normalized === currentReporterName.toLowerCase()) {
                            setSelectedReporterAccountId(detail.ticket.reporter_account_id ?? "");
                          } else {
                            setSelectedReporterAccountId("");
                          }
                        }}
                        placeholder="Search Jira users by name or email"
                        className="min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                      <button
                        type="button"
                        onClick={() => syncReporterMutation.mutate()}
                        disabled={syncReporterMutation.isPending}
                        className="shrink-0 rounded-md border border-blue-300 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {syncReporterMutation.isPending ? "Updating..." : "Update Reporter"}
                      </button>
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {showReporterMatches
                        ? "Pick the correct Jira user below before saving."
                        : "Use this when you need to manually change the reporter."}
                    </div>
                    {showReporterMatches && (
                      <select
                        aria-label="Reporter Matches"
                        value={selectedReporterAccountId}
                        onChange={(e) => {
                          const accountId = e.target.value;
                          setSelectedReporterAccountId(accountId);
                          const selectedOption = sortedReporterOptions.find((option) => option.account_id === accountId);
                          if (selectedOption) {
                            setReporterSearch(selectedOption.display_name);
                          }
                        }}
                        className="mt-2 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      >
                        <option value="">
                          {isSearchingReporters
                            ? "Searching Jira users..."
                            : sortedReporterOptions.length > 0
                              ? "Select reporter match"
                              : "No Jira users found"}
                        </option>
                        {sortedReporterOptions.map((reporter) => (
                          <option key={reporter.account_id} value={reporter.account_id}>
                            {reporter.display_name}
                            {reporter.email_address ? ` (${reporter.email_address})` : ""}
                          </option>
                        ))}
                      </select>
                    )}
                    <div className="mt-1 text-xs text-slate-500">
                      Uses the saved description line like "OCC Ticket Created By: Jane Doe".
                    </div>
                  </div>

                  <label className="block xl:col-span-4">
                    <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Request Type</span>
                    <select
                      value={selectedRequestTypeId}
                      onChange={(e) => setSelectedRequestTypeId(e.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    >
                      <option value="">{effectiveRequestTypeName || "Select request type"}</option>
                      {visibleRequestTypes.map((requestType) => (
                        <option key={requestType.id} value={requestType.id}>
                          {requestType.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-12">
                  <label className="block md:col-span-2 xl:col-span-5">
                    <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Application</span>
                    <input
                      list="ticket-application-options"
                      value={applicationInput}
                      onChange={(e) => setApplicationInput(e.target.value)}
                      placeholder="Portal, Outlook, VPN"
                      className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                    <datalist id="ticket-application-options">
                      {componentOptions.map((component) => (
                        <option key={component} value={component} />
                      ))}
                    </datalist>
                    <div className="mt-1 text-xs text-slate-500">
                      Jira components. Separate multiple applications with commas.
                    </div>
                  </label>

                  <label className="block xl:col-span-3">
                    <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
                      Category
                    </span>
                    <input
                      list="ticket-work-category-options"
                      value={workCategoryInput}
                      onChange={(e) => setWorkCategoryInput(e.target.value)}
                      placeholder="Identity"
                      className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                    <datalist id="ticket-work-category-options">
                      {workCategoryOptions.map((category) => (
                        <option key={category} value={category} />
                      ))}
                    </datalist>
                  </label>

                  <div className="block md:col-span-2 xl:col-span-4">
                    <label className="block">
                      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Status</span>
                      <div className="mt-1 flex flex-col gap-2 sm:flex-row">
                        <select
                          value={selectedTransitionId}
                          onChange={(e) => setSelectedTransitionId(e.target.value)}
                          className="min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                        >
                          <option value="">{detail.ticket.status || "Select status"}</option>
                          {displayTransitions.map((transition: Transition) => (
                            <option key={transition.id} value={transition.id}>
                              {getTransitionLabel(transition)}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          onClick={() => transitionMutation.mutate()}
                          disabled={transitionMutation.isPending || !selectedTransitionId}
                          className="shrink-0 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {transitionMutation.isPending ? "Updating..." : "Change Status"}
                        </button>
                      </div>
                    </label>
                  </div>
                </div>

                <label className="mt-4 block">
                  <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Description</span>
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={8}
                    className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </label>

                {detail.steps_to_recreate && (
                  <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3">
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Steps To Re-Create
                    </h4>
                    <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                      {detail.steps_to_recreate}
                    </div>
                  </div>
                )}

                <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3">
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Ticket Context
                  </h4>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                    {actionContextItems.map((item) => (
                      <div
                        key={item.label}
                        className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"
                      >
                        <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                          {item.label}
                        </div>
                        <div className="mt-1 break-words text-sm font-semibold leading-5 text-slate-900">
                          {String(item.value || "—")}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => saveMutation.mutate()}
                    disabled={saveMutation.isPending}
                    className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {saveMutation.isPending ? "Saving..." : "Save Ticket Details"}
                  </button>
                  <span className="text-xs text-slate-500">
                    Summary, description, reporter, assignee, priority, and request type save here. Status updates separately.
                  </span>
                </div>
              </section>

              <section className="grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
                <div className="space-y-4">
                  <div className="rounded-xl border border-slate-200 p-3">
                    <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-700">Add Comment</h3>
                    <JiraWriteIdentityNotice
                      jiraAuth={me?.jira_auth}
                      className="mt-3"
                    />
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => setCommentAudience("internal")}
                        className={[
                          "rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
                          commentAudience === "internal"
                            ? "border-slate-900 bg-slate-900 text-white"
                            : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50",
                        ].join(" ")}
                      >
                        Internal Note
                      </button>
                      <button
                        type="button"
                        onClick={() => setCommentAudience("customer")}
                        className={[
                          "rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
                          commentAudience === "customer"
                            ? "border-blue-600 bg-blue-600 text-white"
                            : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50",
                        ].join(" ")}
                      >
                        Reply To Customer
                      </button>
                    </div>
                    <textarea
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                      rows={5}
                      placeholder={
                        commentAudience === "customer"
                          ? "Write a reply that will be visible to the customer..."
                          : "Add an internal note for the support team..."
                      }
                      className="mt-3 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                    <div className="mt-3 flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => commentMutation.mutate()}
                        disabled={commentMutation.isPending || !comment.trim()}
                        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {commentMutation.isPending
                          ? "Posting..."
                          : commentAudience === "customer"
                            ? "Send Reply"
                            : "Post Internal Note"}
                      </button>
                      <span className="text-xs text-slate-500">
                        {commentAudience === "customer"
                          ? "Customer replies are posted through Jira Service Management"
                          : "Internal notes stay visible only to agents"}
                      </span>
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-200 p-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
                          Recent Notes & Communications
                        </h3>
                        <div className="mt-1 text-xs text-slate-500">
                          {historyItems.length} total
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => setIsHistoryOpen(true)}
                        disabled={historyItems.length === 0}
                        className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        See History
                      </button>
                    </div>
                    <div className="mt-3 space-y-2">
                      {historyItems.length === 0 && (
                        <div className="text-sm text-slate-500">No notes or customer communications yet.</div>
                      )}
                      {recentHistoryItems.map((item) => (
                        <div key={item.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                          <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-slate-700">{item.author}</span>
                              <span className={chipClass(item.public ? "blue" : "slate")}>
                                {item.public ? "Customer Reply" : "Internal Note"}
                              </span>
                            </div>
                            <span>{formatDateTime(item.created)}</span>
                          </div>
                          <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                            {item.body || "Empty comment"}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <div className="rounded-xl border border-slate-200 p-3">
                    <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-700">Labels And Components</h3>
                    <div className="mt-3 space-y-3 text-sm text-slate-700">
                      <div>
                        <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Labels</div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {detail.ticket.labels.length === 0 && <span className="text-slate-400">None</span>}
                          {detail.ticket.labels.map((label) => (
                            <span key={label} className={chipClass("slate")}>
                              {label}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                          Application
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {detail.ticket.components.length === 0 && <span className="text-slate-400">None</span>}
                          {detail.ticket.components.map((component) => (
                            <span key={component} className={chipClass("slate")}>
                              {component}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Organizations</div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {detail.ticket.organizations.length === 0 && <span className="text-slate-400">None</span>}
                          {detail.ticket.organizations.map((organization) => (
                            <span key={organization} className={chipClass("slate")}>
                              {organization}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-200 p-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-700">Attachments</h3>
                      <span className="text-xs text-slate-500">{detail.attachments.length} files</span>
                    </div>
                    <div className="mt-3 space-y-2">
                      {detail.attachments.length === 0 && (
                        <div className="text-sm text-slate-500">No attachments on this ticket.</div>
                      )}
                      {detail.attachments.map((attachment) => (
                        <div
                          key={attachment.id}
                          className="rounded-lg border border-slate-200 px-3 py-3"
                        >
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                              {attachment.preview_kind === "image" && attachment.preview_available && attachment.preview_url ? (
                                <button
                                  type="button"
                                  onClick={() => setPreviewAttachment(attachment)}
                                  className="mb-3 block overflow-hidden rounded-xl border border-slate-200 bg-slate-50 hover:border-blue-200 hover:bg-blue-50"
                                >
                                  <img
                                    src={attachment.thumbnail_url || attachment.preview_url}
                                    alt={attachment.display_name}
                                    loading="lazy"
                                    className="max-h-64 w-full object-contain"
                                  />
                                </button>
                              ) : null}
                              <div className="truncate text-sm font-medium text-slate-800">
                                {attachment.display_name}
                              </div>
                              {attachment.raw_filename && attachment.raw_filename !== attachment.display_name ? (
                                <div className="mt-1 truncate text-xs text-slate-400">
                                  Jira file: {attachment.raw_filename}
                                </div>
                              ) : null}
                              <div className="mt-2 text-xs text-slate-500">
                                {formatAttachmentType(attachment)} • {formatBytes(attachment.size)} • {attachment.author || "Unknown author"}
                              </div>
                            </div>
                            <div className="text-right">
                              <div className="text-xs text-slate-500">{formatDateTime(attachment.created)}</div>
                              <div className="mt-2 flex flex-wrap justify-end gap-2">
                                <button
                                  type="button"
                                  disabled={!attachment.preview_available}
                                  onClick={() => setPreviewAttachment(attachment)}
                                  className={`rounded-md px-2.5 py-1.5 text-xs font-medium ${
                                    attachment.preview_available
                                      ? "border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100"
                                      : "cursor-not-allowed border border-slate-200 bg-slate-100 text-slate-400"
                                  }`}
                                >
                                  {previewButtonLabel(attachment)}
                                </button>
                                <a
                                  href={attachment.download_url || attachment.content_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                                >
                                  Download
                                </a>
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-200 p-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-700">Linked Issues</h3>
                      <span className="text-xs text-slate-500">{detail.issue_links.length} links</span>
                    </div>
                    <div className="mt-3 space-y-2">
                      {detail.issue_links.length === 0 && (
                        <div className="text-sm text-slate-500">No linked issues.</div>
                      )}
                      {detail.issue_links.map((link) => (
                        <a
                          key={`${link.direction}-${link.key}-${link.relationship}`}
                          href={link.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block rounded-lg border border-slate-200 px-3 py-3 hover:bg-slate-50"
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <div className="font-mono text-xs font-semibold uppercase tracking-wide text-blue-700">
                                {link.key}
                              </div>
                              <div className="mt-1 text-sm text-slate-800">{link.summary || "No summary"}</div>
                              <div className="mt-1 text-xs text-slate-500">
                                {link.relationship || link.type || "Linked issue"}
                              </div>
                            </div>
                            <span className={chipClass("slate")}>{link.status || "Unknown"}</span>
                          </div>
                        </a>
                      ))}
                    </div>
                  </div>

                  <details className="rounded-xl border border-slate-200 p-3">
                    <summary className="cursor-pointer text-sm font-semibold uppercase tracking-wide text-slate-700">
                      Raw Jira Payload
                    </summary>
                    <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-950 p-4 text-xs leading-5 text-slate-100">
                      {JSON.stringify(detail.raw_issue, null, 2)}
                    </pre>
                  </details>
                </div>
              </section>

              <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
                      Technician QA
                    </h3>
                    <p className="mt-1 text-sm text-slate-500">
                      AI review of technician communication and documentation quality for this ticket.
                    </p>
                  </div>
                  {technicianScore ? (
                    <div className="rounded-xl bg-white px-3 py-2 text-right shadow-sm">
                      <div className="text-[11px] uppercase tracking-wide text-slate-400">Overall</div>
                      <div className="text-lg font-semibold text-slate-900">
                        {formatScore(technicianScore.overall_score)}
                      </div>
                    </div>
                  ) : null}
                </div>

                {isLoadingTechnicianScores ? (
                  <div className="mt-4 rounded-lg border border-slate-200 bg-white px-4 py-6 text-sm text-slate-500">
                    Loading technician QA score...
                  </div>
                ) : !technicianScore ? (
                  <div className="mt-4 rounded-lg border border-dashed border-slate-300 bg-white px-4 py-6 text-sm text-slate-500">
                    No technician QA score yet for this ticket.
                  </div>
                ) : (
                  <>
                    <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                      <div className="rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm">
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Communication</div>
                        <div className="mt-2 text-2xl font-semibold text-blue-700">
                          {formatScore(technicianScore.communication_score)}
                        </div>
                      </div>
                      <div className="rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm">
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Documentation</div>
                        <div className="mt-2 text-2xl font-semibold text-amber-700">
                          {formatScore(technicianScore.documentation_score)}
                        </div>
                      </div>
                      <div className="rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm">
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Model</div>
                        <div className="mt-2 break-words text-sm font-semibold text-slate-900">
                          {technicianScore.model_used || "—"}
                        </div>
                      </div>
                      <div className="rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm">
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Scored</div>
                        <div className="mt-2 text-sm font-semibold text-slate-900">
                          {formatDateTime(technicianScore.created_at)}
                        </div>
                      </div>
                    </div>

                    <div className="mt-4 grid gap-3 lg:grid-cols-2">
                      <div className="rounded-xl border border-slate-200 bg-white px-4 py-4 shadow-sm">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                            Communication Notes
                          </span>
                          <span className={chipClass("blue")}>{formatScore(technicianScore.communication_score)}</span>
                        </div>
                        <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                          {technicianScore.communication_notes || "No communication notes."}
                        </p>
                      </div>
                      <div className="rounded-xl border border-slate-200 bg-white px-4 py-4 shadow-sm">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                            Documentation Notes
                          </span>
                          <span className={chipClass("amber")}>{formatScore(technicianScore.documentation_score)}</span>
                        </div>
                        <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                          {technicianScore.documentation_notes || "No documentation notes."}
                        </p>
                      </div>
                    </div>

                    <div className="mt-4 rounded-xl border border-slate-200 bg-white px-4 py-4 shadow-sm">
                      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Summary</div>
                      <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                        {technicianScore.score_summary || "No technician QA summary."}
                      </p>
                    </div>
                  </>
                )}
              </section>
            </>
          )}
        </div>

      </aside>

      {previewAttachment && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/45 p-5"
          onClick={(event) => {
            event.stopPropagation();
            setPreviewAttachment(null);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="ticket-attachment-preview-title"
            className="flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="border-b border-slate-200 px-5 py-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h3
                    id="ticket-attachment-preview-title"
                    className="truncate text-lg font-semibold text-slate-900"
                  >
                    {previewAttachment.display_name}
                  </h3>
                  <div className="mt-1 flex flex-wrap gap-2 text-sm text-slate-500">
                    <span>{formatAttachmentType(previewAttachment)}</span>
                    <span>•</span>
                    <span>{formatBytes(previewAttachment.size)}</span>
                    <span>•</span>
                    <span>{formatDateTime(previewAttachment.created)}</span>
                  </div>
                  {previewAttachment.raw_filename && previewAttachment.raw_filename !== previewAttachment.display_name ? (
                    <div className="mt-2 text-xs text-slate-400">
                      Jira filename: {previewAttachment.raw_filename}
                    </div>
                  ) : null}
                </div>
                <div className="flex items-center gap-2">
                  <a
                    href={previewAttachment.download_url || previewAttachment.content_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded-md border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Download
                  </a>
                  <button
                    type="button"
                    onClick={() => setPreviewAttachment(null)}
                    className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Close
                  </button>
                </div>
              </div>
            </div>

            <div className="overflow-auto bg-slate-50 px-5 py-4">
              {!previewAttachment.preview_available ? (
                <div className="rounded-xl border border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">
                  Preview is not available for this attachment type.
                </div>
              ) : isPreviewLoading ? (
                <div className="rounded-xl border border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-500">
                  Loading attachment preview...
                </div>
              ) : previewError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-6 text-sm text-red-700">
                  {previewError}
                </div>
              ) : previewAttachment.preview_kind === "text" ? (
                <pre className="overflow-auto rounded-xl border border-slate-200 bg-white px-4 py-4 text-sm leading-6 text-slate-700">
                  {previewText || "No preview text available."}
                </pre>
              ) : previewAttachment.preview_kind === "image" && previewObjectUrl ? (
                <div className="flex justify-center rounded-xl border border-slate-200 bg-white p-4">
                  <img
                    src={previewObjectUrl}
                    alt={previewAttachment.display_name}
                    className="max-h-[72vh] max-w-full rounded-lg object-contain"
                  />
                </div>
              ) : isIframePreviewKind(previewAttachment.preview_kind) && previewAttachment.preview_url ? (
                <iframe
                  title={`${previewAttachment.display_name} preview`}
                  src={previewAttachment.preview_url}
                  className="h-[72vh] w-full rounded-xl border border-slate-200 bg-white"
                />
              ) : (
                <div className="rounded-xl border border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">
                  Preview is not available for this attachment.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {isHistoryOpen && detail && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/45 p-5"
          onClick={(event) => {
            event.stopPropagation();
            setIsHistoryOpen(false);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="ticket-history-title"
            className="flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="border-b border-slate-200 px-5 py-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3
                    id="ticket-history-title"
                    className="text-lg font-semibold text-slate-900"
                  >
                    Ticket History
                  </h3>
                  <p className="mt-1 text-sm text-slate-500">
                    All internal notes and customer-facing communications for {ticket?.key ?? ticketKey}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <span className={chipClass("slate")}>
                      {internalNoteCount} internal note{internalNoteCount === 1 ? "" : "s"}
                    </span>
                    <span className={chipClass("blue")}>
                      {customerReplyCount} customer repl{customerReplyCount === 1 ? "y" : "ies"}
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setIsHistoryOpen(false)}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Close
                </button>
              </div>
            </div>

            <div className="overflow-y-auto px-5 py-4">
              <div className="space-y-4">
                {historyItems.length === 0 && (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
                    No history yet.
                  </div>
                )}
                {historyItems.map((item) => (
                  <article
                    key={item.id}
                    className="rounded-2xl border border-slate-200 bg-slate-50 p-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-slate-900">{item.author}</span>
                        <span className={chipClass(item.public ? "blue" : "slate")}>
                          {item.public ? "Customer Reply" : "Internal Note"}
                        </span>
                      </div>
                      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
                        {formatDateTime(item.created)}
                      </span>
                    </div>
                    <div className="mt-3 whitespace-pre-wrap text-[15px] leading-7 text-slate-700">
                      {item.body || "Empty comment"}
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
