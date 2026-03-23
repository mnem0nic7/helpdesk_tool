import { useState, useEffect } from "react";
import { api } from "../lib/api.ts";
import { logClientError } from "../lib/errorLogging.ts";
import type { Transition, Assignee, BulkResult } from "../lib/api.ts";
import ConfirmModal from "./ConfirmModal.tsx";
import type { BulkActionResult } from "./ConfirmModal.tsx";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ActionType = "status" | "assign" | "priority" | "comment" | null;

interface BulkActionsToolbarProps {
  selectedKeys: string[];
  onActionComplete: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function BulkActionsToolbar({
  selectedKeys,
  onActionComplete,
}: BulkActionsToolbarProps) {
  const [activeAction, setActiveAction] = useState<ActionType>(null);

  // Form values
  const [selectedTransition, setSelectedTransition] = useState("");
  const [selectedAssignee, setSelectedAssignee] = useState("");
  const [selectedPriority, setSelectedPriority] = useState("");
  const [commentText, setCommentText] = useState("");

  // Fetched data for dropdowns
  const [transitions, setTransitions] = useState<Transition[]>([]);
  const [assignees, setAssignees] = useState<Assignee[]>([]);
  const [fetchingDropdown, setFetchingDropdown] = useState(false);

  // Confirm modal state
  const [showConfirm, setShowConfirm] = useState(false);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [confirmResult, setConfirmResult] = useState<BulkActionResult | undefined>(undefined);
  const [confirmTitle, setConfirmTitle] = useState("");
  const [confirmDescription, setConfirmDescription] = useState("");

  const PRIORITIES = ["Highest", "High", "Medium", "Low", "Lowest"];

  // Reset form when action type changes
  useEffect(() => {
    setSelectedTransition("");
    setSelectedAssignee("");
    setSelectedPriority("");
    setCommentText("");
  }, [activeAction]);

  // Fetch transitions when "Change Status" is opened
  async function handleOpenStatus() {
    if (activeAction === "status") {
      setActiveAction(null);
      return;
    }
    setActiveAction("status");
    setFetchingDropdown(true);
    try {
      // Fetch transitions for the first selected ticket
      const t = await api.getTransitions(selectedKeys[0]);
      setTransitions(t);
    } catch (err) {
      logClientError("Failed to load bulk status transitions", err, {
        selectedKeys,
      });
      setTransitions([]);
    }
    setFetchingDropdown(false);
  }

  // Fetch assignees when "Reassign" is opened
  async function handleOpenAssign() {
    if (activeAction === "assign") {
      setActiveAction(null);
      return;
    }
    setActiveAction("assign");
    setFetchingDropdown(true);
    try {
      const a = await api.getAssignees();
      setAssignees(a);
    } catch (err) {
      logClientError("Failed to load bulk assignees", err, {
        selectedKeys,
      });
      setAssignees([]);
    }
    setFetchingDropdown(false);
  }

  function handleOpenPriority() {
    setActiveAction(activeAction === "priority" ? null : "priority");
  }

  function handleOpenComment() {
    setActiveAction(activeAction === "comment" ? null : "comment");
  }

  // ---------------------------------------------------------------------------
  // Apply logic: opens the confirmation modal
  // ---------------------------------------------------------------------------

  function handleApply() {
    let title = "";
    let description = "";

    switch (activeAction) {
      case "status": {
        const t = transitions.find((tr) => tr.id === selectedTransition);
        title = "Confirm Status Change";
        description = `Transition ${selectedKeys.length} ticket${selectedKeys.length !== 1 ? "s" : ""} to "${t?.name ?? "unknown"}".`;
        break;
      }
      case "assign": {
        const a = assignees.find((as) => as.account_id === selectedAssignee);
        title = "Confirm Reassignment";
        description = `Reassign ${selectedKeys.length} ticket${selectedKeys.length !== 1 ? "s" : ""} to "${a?.display_name ?? "Unassigned"}".`;
        break;
      }
      case "priority":
        title = "Confirm Priority Change";
        description = `Set priority to "${selectedPriority}" for ${selectedKeys.length} ticket${selectedKeys.length !== 1 ? "s" : ""}.`;
        break;
      case "comment":
        title = "Confirm Add Comment";
        description = `Add a comment to ${selectedKeys.length} ticket${selectedKeys.length !== 1 ? "s" : ""}.`;
        break;
      default:
        return;
    }

    setConfirmTitle(title);
    setConfirmDescription(description);
    setConfirmResult(undefined);
    setShowConfirm(true);
  }

  // ---------------------------------------------------------------------------
  // Execute the bulk action
  // ---------------------------------------------------------------------------

  function parseResults(results: BulkResult[]): BulkActionResult {
    const success: string[] = [];
    const failed: { key: string; error: string }[] = [];
    for (const r of results) {
      if (r.success) {
        success.push(r.key);
      } else {
        failed.push({ key: r.key, error: r.error ?? "Unknown error" });
      }
    }
    return { success, failed };
  }

  async function handleConfirm() {
    setConfirmLoading(true);
    try {
      let results: BulkResult[] = [];
      switch (activeAction) {
        case "status":
          results = await api.bulkStatus(selectedKeys, selectedTransition);
          break;
        case "assign":
          results = await api.bulkAssign(selectedKeys, selectedAssignee);
          break;
        case "priority":
          results = await api.bulkPriority(selectedKeys, selectedPriority);
          break;
        case "comment":
          results = await api.bulkComment(selectedKeys, commentText);
          break;
      }
      setConfirmResult(parseResults(results));
    } catch (err) {
      logClientError("Bulk action failed", err, {
        action: activeAction,
        selectedKeys,
      });
      setConfirmResult({
        success: [],
        failed: selectedKeys.map((k) => ({
          key: k,
          error: err instanceof Error ? err.message : "Unknown error",
        })),
      });
    }
    setConfirmLoading(false);
  }

  function handleModalClose() {
    const hadResult = confirmResult !== undefined;
    setShowConfirm(false);
    setConfirmResult(undefined);
    setConfirmLoading(false);
    if (hadResult) {
      setActiveAction(null);
      onActionComplete();
    }
  }

  // ---------------------------------------------------------------------------
  // Can the user click Apply?
  // ---------------------------------------------------------------------------

  function isApplyDisabled(): boolean {
    switch (activeAction) {
      case "status":
        return !selectedTransition;
      case "assign":
        return !selectedAssignee;
      case "priority":
        return !selectedPriority;
      case "comment":
        return !commentText.trim();
      default:
        return true;
    }
  }

  // ---------------------------------------------------------------------------
  // Styles
  // ---------------------------------------------------------------------------

  const actionBtnBase =
    "h-8 rounded-md border px-3 text-sm font-medium transition-colors";
  const actionBtnActive =
    "border-blue-600 bg-blue-600 text-white";
  const actionBtnInactive =
    "border-gray-300 bg-white text-gray-700 hover:bg-gray-50 shadow-sm";

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (selectedKeys.length === 0) return null;

  return (
    <>
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
        {/* Top row: count + action buttons */}
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-blue-800">
            {selectedKeys.length} ticket{selectedKeys.length !== 1 ? "s" : ""} selected
          </span>

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={handleOpenStatus}
              className={`${actionBtnBase} ${activeAction === "status" ? actionBtnActive : actionBtnInactive}`}
            >
              Change Status
            </button>
            <button
              type="button"
              onClick={handleOpenAssign}
              className={`${actionBtnBase} ${activeAction === "assign" ? actionBtnActive : actionBtnInactive}`}
            >
              Reassign
            </button>
            <button
              type="button"
              onClick={handleOpenPriority}
              className={`${actionBtnBase} ${activeAction === "priority" ? actionBtnActive : actionBtnInactive}`}
            >
              Change Priority
            </button>
            <button
              type="button"
              onClick={handleOpenComment}
              className={`${actionBtnBase} ${activeAction === "comment" ? actionBtnActive : actionBtnInactive}`}
            >
              Add Comment
            </button>
          </div>
        </div>

        {/* Action form */}
        {activeAction && (
          <div className="mt-3 flex items-end gap-3 border-t border-blue-200 pt-3">
            {/* Status dropdown */}
            {activeAction === "status" && (
              fetchingDropdown ? (
                <div className="flex items-center gap-2 text-sm text-gray-500">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
                  Loading transitions...
                </div>
              ) : (
                <select
                  value={selectedTransition}
                  onChange={(e) => setSelectedTransition(e.target.value)}
                  className="h-9 min-w-[200px] rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="">Select a transition...</option>
                  {transitions.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name} {t.to_status ? `(-> ${t.to_status})` : ""}
                    </option>
                  ))}
                </select>
              )
            )}

            {/* Assign dropdown */}
            {activeAction === "assign" && (
              fetchingDropdown ? (
                <div className="flex items-center gap-2 text-sm text-gray-500">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
                  Loading assignees...
                </div>
              ) : (
                <select
                  value={selectedAssignee}
                  onChange={(e) => setSelectedAssignee(e.target.value)}
                  className="h-9 min-w-[200px] rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="">Select an assignee...</option>
                  {assignees.map((a) => (
                    <option key={a.account_id} value={a.account_id}>
                      {a.display_name}
                    </option>
                  ))}
                </select>
              )
            )}

            {/* Priority dropdown */}
            {activeAction === "priority" && (
              <select
                value={selectedPriority}
                onChange={(e) => setSelectedPriority(e.target.value)}
                className="h-9 min-w-[200px] rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="">Select priority...</option>
                {PRIORITIES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            )}

            {/* Comment textarea */}
            {activeAction === "comment" && (
              <textarea
                value={commentText}
                onChange={(e) => setCommentText(e.target.value)}
                placeholder="Enter comment text..."
                rows={2}
                className="min-w-[300px] flex-1 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            )}

            {/* Apply button */}
            {!fetchingDropdown && (
              <button
                type="button"
                onClick={handleApply}
                disabled={isApplyDisabled()}
                className="h-9 rounded-md border border-transparent bg-blue-600 px-4 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Apply
              </button>
            )}
          </div>
        )}
      </div>

      {/* Confirmation modal */}
      <ConfirmModal
        isOpen={showConfirm}
        onClose={handleModalClose}
        onConfirm={handleConfirm}
        title={confirmTitle}
        description={confirmDescription}
        ticketKeys={selectedKeys}
        loading={confirmLoading}
        result={confirmResult}
      />
    </>
  );
}
