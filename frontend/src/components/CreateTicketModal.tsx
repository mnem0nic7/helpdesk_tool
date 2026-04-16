import { useEffect, useState } from "react";
import type { PriorityOption, RequestTypeOption, TicketCreatePayload } from "../lib/api.ts";

const EMPTY_CREATE_FORM: TicketCreatePayload = {
  summary: "",
  description: "",
  priority: "",
  request_type_id: "",
};

interface CreateTicketModalProps {
  isOpen: boolean;
  priorities: PriorityOption[];
  requestTypes: RequestTypeOption[];
  isLoadingOptions: boolean;
  isSubmitting: boolean;
  errorText: string;
  onClose: () => void;
  onSubmit: (payload: TicketCreatePayload) => void;
}

export default function CreateTicketModal({
  isOpen,
  priorities,
  requestTypes,
  isLoadingOptions,
  isSubmitting,
  errorText,
  onClose,
  onSubmit,
}: CreateTicketModalProps) {
  const [form, setForm] = useState<TicketCreatePayload>(EMPTY_CREATE_FORM);

  useEffect(() => {
    if (!isOpen) {
      setForm(EMPTY_CREATE_FORM);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const isSubmitDisabled =
    isSubmitting ||
    isLoadingOptions ||
    !form.summary.trim() ||
    !form.priority.trim() ||
    !form.request_type_id.trim();

  const handleChange = (field: keyof TicketCreatePayload, value: string) => {
    setForm((current) => ({ ...current, [field]: value }));
  };

  const handleSubmit = () => {
    onSubmit({
      summary: form.summary.trim(),
      description: form.description,
      priority: form.priority.trim(),
      request_type_id: form.request_type_id.trim(),
    });
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/45 p-5" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-ticket-title"
        className="w-full max-w-3xl rounded-2xl bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="border-b border-slate-200 px-6 py-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 id="create-ticket-title" className="text-xl font-semibold text-slate-900">
                Create Ticket
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Create a new OIT service request without leaving it-app.
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Close
            </button>
          </div>
        </div>

        <div className="space-y-5 px-6 py-5">
          {errorText && (
            <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {errorText}
            </div>
          )}

          <div className="space-y-2">
            <label htmlFor="create-ticket-summary" className="text-sm font-medium text-slate-700">
              Summary
            </label>
            <input
              id="create-ticket-summary"
              type="text"
              value={form.summary}
              onChange={(event) => handleChange("summary", event.target.value)}
              placeholder="Brief description of the request"
              className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              disabled={isSubmitting}
              autoFocus
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label htmlFor="create-ticket-priority" className="text-sm font-medium text-slate-700">
                Priority
              </label>
              <select
                id="create-ticket-priority"
                value={form.priority}
                onChange={(event) => handleChange("priority", event.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                disabled={isSubmitting || isLoadingOptions}
              >
                <option value="">{isLoadingOptions ? "Loading priorities..." : "Select priority"}</option>
                {priorities.map((priority) => (
                  <option key={priority.id || priority.name} value={priority.name}>
                    {priority.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-2">
              <label htmlFor="create-ticket-request-type" className="text-sm font-medium text-slate-700">
                Request Type
              </label>
              <select
                id="create-ticket-request-type"
                value={form.request_type_id}
                onChange={(event) => handleChange("request_type_id", event.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                disabled={isSubmitting || isLoadingOptions}
              >
                <option value="">{isLoadingOptions ? "Loading request types..." : "Select request type"}</option>
                {requestTypes.map((requestType) => (
                  <option key={requestType.id} value={requestType.id}>
                    {requestType.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-2">
            <label htmlFor="create-ticket-description" className="text-sm font-medium text-slate-700">
              Description
            </label>
            <textarea
              id="create-ticket-description"
              value={form.description}
              onChange={(event) => handleChange("description", event.target.value)}
              placeholder="Add any helpful background, symptoms, or requested action."
              rows={8}
              className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              disabled={isSubmitting}
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-slate-200 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={isSubmitDisabled}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
          >
            {isSubmitting ? "Creating..." : "Create Ticket"}
          </button>
        </div>
      </div>
    </div>
  );
}
