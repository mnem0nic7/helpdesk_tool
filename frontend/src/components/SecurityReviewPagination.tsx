import { useEffect, useMemo, useState } from "react";

export const SECURITY_REVIEW_PAGE_SIZE_OPTIONS = [25, 50, 100];

export function useSecurityReviewPagination(resetKey: string, itemCount: number, defaultPageSize = 50) {
  const [pageSize, setPageSize] = useState(defaultPageSize);
  const [currentPage, setCurrentPage] = useState(1);

  useEffect(() => {
    setCurrentPage(1);
  }, [pageSize, resetKey]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(itemCount / pageSize)),
    [itemCount, pageSize],
  );

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  const pageStart = itemCount === 0 ? 0 : (currentPage - 1) * pageSize;
  const pageEnd = itemCount === 0 ? 0 : Math.min(pageStart + pageSize, itemCount);

  return {
    currentPage,
    pageEnd,
    pageSize,
    pageStart,
    setCurrentPage,
    setPageSize,
    totalPages,
  };
}

export function sliceSecurityReviewPage<T>(items: T[], pageStart: number, pageSize: number): T[] {
  return items.slice(pageStart, pageStart + pageSize);
}

export default function SecurityReviewPagination({
  count,
  currentPage,
  pageSize,
  setCurrentPage,
  setPageSize,
  totalPages,
  noun,
}: {
  count: number;
  currentPage: number;
  pageSize: number;
  setCurrentPage: (value: number | ((current: number) => number)) => void;
  setPageSize: (value: number) => void;
  totalPages: number;
  noun: string;
}) {
  const pageStart = count === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const pageEnd = count === 0 ? 0 : Math.min(currentPage * pageSize, count);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-slate-50 px-4 py-3">
      <div className="text-sm text-slate-600">
        Showing {pageStart}-{pageEnd} of {count.toLocaleString()} {noun}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Page size
          <select
            value={pageSize}
            onChange={(event) => setPageSize(Number(event.target.value))}
            className="ml-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
          >
            {SECURITY_REVIEW_PAGE_SIZE_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
          disabled={currentPage <= 1}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
        >
          Previous
        </button>
        <div className="min-w-[112px] text-center text-sm text-slate-600">
          Page {count === 0 ? 0 : currentPage} of {count === 0 ? 0 : totalPages}
        </div>
        <button
          type="button"
          onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
          disabled={count === 0 || currentPage >= totalPages}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
        >
          Next
        </button>
      </div>
    </div>
  );
}
