import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type AzureQuickJumpResult } from "../lib/api.ts";

const ICONS: Record<AzureQuickJumpResult["kind"], string> = {
  page: "P",
  vm: "VM",
  desktop: "AVD",
  resource: "R",
  user: "U",
  group: "G",
  enterprise_app: "EA",
  app_registration: "AR",
  directory_role: "DR",
};

function resultLabel(result: AzureQuickJumpResult): string {
  return ICONS[result.kind] || result.kind.slice(0, 2).toUpperCase();
}

export default function AzureQuickJump() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const trimmedQuery = query.trim();
  const { data, isFetching } = useQuery({
    queryKey: ["azure", "quick-jump", trimmedQuery],
    queryFn: () => api.getAzureQuickJump(trimmedQuery),
    enabled: open && trimmedQuery.length >= 2,
    staleTime: 15_000,
  });

  const results = useMemo(() => data?.results ?? [], [data]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
      if (event.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function handleSelect(result: AzureQuickJumpResult) {
    navigate(result.route);
    setOpen(false);
    setQuery("");
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
        title="Quick jump"
      >
        Search Azure
        <span className="ml-2 rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">Ctrl/Cmd+K</span>
      </button>

      {open ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-950/45 px-4 pt-20" onClick={() => setOpen(false)}>
          <div
            className="w-full max-w-2xl overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="border-b border-slate-200 px-5 py-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Quick Jump</div>
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search pages, users, apps, VMs, desktops, and resources..."
                className="mt-3 w-full rounded-xl border border-slate-300 px-3 py-3 text-sm outline-none transition focus:border-sky-500"
              />
            </div>
            <div className="max-h-[28rem] overflow-y-auto">
              {!trimmedQuery ? (
                <div className="px-5 py-6 text-sm text-slate-500">
                  Search across Azure pages and cached entities. Use page results for navigation and entity results for direct drill-ins.
                </div>
              ) : null}
              {trimmedQuery.length === 1 ? (
                <div className="px-5 py-6 text-sm text-slate-500">Type at least 2 characters to search the Azure cache.</div>
              ) : null}
              {trimmedQuery.length >= 2 && isFetching ? (
                <div className="px-5 py-6 text-sm text-slate-500">Searching Azure pages and cached entities...</div>
              ) : null}
              {trimmedQuery.length >= 2 && !isFetching && results.length === 0 ? (
                <div className="px-5 py-6 text-sm text-slate-500">No quick-jump matches were found for this search.</div>
              ) : null}
              {results.map((result) => (
                <button
                  key={`${result.kind}-${result.id}-${result.route}`}
                  type="button"
                  onClick={() => handleSelect(result)}
                  className="flex w-full items-start gap-3 border-t border-slate-100 px-5 py-4 text-left transition hover:bg-slate-50"
                >
                  <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-sky-50 text-[11px] font-semibold text-sky-700">
                    {resultLabel(result)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-slate-900">{result.label}</span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                        {result.kind.replaceAll("_", " ")}
                      </span>
                    </div>
                    <div className="mt-1 text-sm text-slate-500">{result.subtitle || "Open this Azure portal view."}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
