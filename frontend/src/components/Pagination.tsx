interface PaginationProps {
  page: number;
  hasMore: boolean;
  onPageChange: (page: number) => void;
}

export default function Pagination({
  page,
  hasMore,
  onPageChange,
}: PaginationProps) {
  const isFirst = page <= 1;

  return (
    <div className="flex items-center justify-end">
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
          Page {page}
        </span>

        <button
          type="button"
          disabled={!hasMore}
          onClick={() => onPageChange(page + 1)}
          className={[
            "rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
            !hasMore
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
