interface BulkFailure {
  key: string;
  error: string;
}

interface BulkActionResult {
  success: string[];
  failed: BulkFailure[];
}

interface ConfirmModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description: string;
  ticketKeys: string[];
  loading?: boolean;
  result?: BulkActionResult;
}

export type { BulkActionResult, BulkFailure };

export default function ConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  title,
  description,
  ticketKeys,
  loading = false,
  result,
}: ConfirmModalProps) {
  if (!isOpen) return null;

  const hasResult = result !== undefined;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Dark overlay */}
      <div
        className="absolute inset-0 bg-black/50"
        onClick={!loading ? onClose : undefined}
      />

      {/* Modal card */}
      <div className="relative z-10 w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
        {/* Title */}
        <h3 className="text-lg font-semibold text-gray-900">{title}</h3>

        {/* Description */}
        <p className="mt-2 text-sm text-gray-600">{description}</p>

        {/* Ticket keys list */}
        {!hasResult && (
          <div className="mt-4">
            <p className="text-xs font-medium uppercase tracking-wider text-gray-500">
              Affected tickets ({ticketKeys.length})
            </p>
            <div className="mt-1 max-h-40 overflow-y-auto rounded border border-gray-200 bg-gray-50 p-2">
              <div className="flex flex-wrap gap-1">
                {ticketKeys.map((key) => (
                  <span
                    key={key}
                    className="inline-block rounded bg-blue-100 px-2 py-0.5 font-mono text-xs text-blue-800"
                  >
                    {key}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Loading spinner */}
        {loading && (
          <div className="mt-4 flex items-center justify-center py-4">
            <div className="h-6 w-6 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
            <span className="ml-3 text-sm text-gray-500">
              Processing {ticketKeys.length} ticket{ticketKeys.length !== 1 ? "s" : ""}...
            </span>
          </div>
        )}

        {/* Result display */}
        {hasResult && !loading && (
          <div className="mt-4 space-y-3">
            {result.success.length > 0 && (
              <div className="rounded border border-green-200 bg-green-50 px-3 py-2">
                <p className="text-sm font-medium text-green-800">
                  {result.success.length} ticket{result.success.length !== 1 ? "s" : ""} updated successfully
                </p>
              </div>
            )}
            {result.failed.length > 0 && (
              <div className="rounded border border-red-200 bg-red-50 px-3 py-2">
                <p className="text-sm font-medium text-red-800">
                  {result.failed.length} ticket{result.failed.length !== 1 ? "s" : ""} failed
                </p>
                <ul className="mt-1 space-y-1">
                  {result.failed.map((f) => (
                    <li key={f.key} className="text-xs text-red-700">
                      <span className="font-mono font-semibold">{f.key}</span>: {f.error}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Buttons */}
        <div className="mt-6 flex justify-end gap-3">
          {hasResult && !loading ? (
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
            >
              Close
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={onClose}
                disabled={loading}
                className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={onConfirm}
                disabled={loading}
                className="rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Confirm
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
