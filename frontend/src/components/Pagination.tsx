interface PaginationProps {
  page: number;
  totalPages: number;
  total: number;
  onPageChange: (page: number) => void;
}

export default function Pagination({
  page,
  totalPages,
  total,
  onPageChange,
}: PaginationProps) {
  const isFirst = page <= 1;
  const isLast = page >= totalPages;

  return (
    <div className="flex items-center justify-between">
      {/* Total count */}
      <span className="text-sm text-gray-500">
        {total.toLocaleString()} ticket{total !== 1 ? "s" : ""} total
      </span>

      {/* Navigation */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={isFirst}
          onClick={() => onPageChange(page - 1)}
          className={[
            "rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
            isFirst
              ? "cursor-not-allowed border-gray-200 bg-gray-100 text-gray-400"
              : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50 shadow-sm",
          ].join(" ")}
        >
          Prev
        </button>

        <span className="px-2 text-sm text-gray-600">
          Page {page} of {totalPages || 1}
        </span>

        <button
          type="button"
          disabled={isLast}
          onClick={() => onPageChange(page + 1)}
          className={[
            "rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
            isLast
              ? "cursor-not-allowed border-gray-200 bg-gray-100 text-gray-400"
              : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50 shadow-sm",
          ].join(" ")}
        >
          Next
        </button>
      </div>
    </div>
  );
}
