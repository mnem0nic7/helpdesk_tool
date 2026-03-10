import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type {
  KnowledgeBaseArticle,
  KnowledgeBaseArticleUpsertPayload,
} from "../lib/api.ts";
import { getSiteBranding } from "../lib/siteContext.ts";

type EditorState = KnowledgeBaseArticleUpsertPayload & {
  id: number | null;
  code: string;
  source_filename: string;
  imported_from_seed: boolean;
  ai_generated: boolean;
};

function toEditorState(article: KnowledgeBaseArticle): EditorState {
  return {
    id: article.id,
    code: article.code,
    title: article.title,
    request_type: article.request_type,
    summary: article.summary,
    content: article.content,
    source_ticket_key: article.source_ticket_key,
    source_filename: article.source_filename,
    imported_from_seed: article.imported_from_seed,
    ai_generated: article.ai_generated,
  };
}

function emptyEditorState(): EditorState {
  return {
    id: null,
    code: "",
    title: "",
    request_type: "",
    summary: "",
    content: "",
    source_ticket_key: "",
    source_filename: "",
    imported_from_seed: false,
    ai_generated: false,
  };
}

function formatTimestamp(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function KnowledgeBasePage() {
  const branding = getSiteBranding();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [requestTypeFilter, setRequestTypeFilter] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [editor, setEditor] = useState<EditorState>(emptyEditorState());
  const [ticketKey, setTicketKey] = useState("");
  const [message, setMessage] = useState<{ type: "info" | "error"; text: string } | null>(null);

  const { data: requestTypes = [] } = useQuery({
    queryKey: ["request-types"],
    queryFn: () => api.getRequestTypes(),
  });

  const { data: articles = [], isLoading } = useQuery({
    queryKey: ["kb-articles", search, requestTypeFilter],
    queryFn: () => api.getKnowledgeBaseArticles(search, requestTypeFilter),
  });

  useEffect(() => {
    if (!articles.length) {
      setSelectedId(null);
      setEditor((current) => (current.id === null ? current : emptyEditorState()));
      return;
    }
    if (isCreatingNew) {
      return;
    }
    const selected = articles.find((article) => article.id === selectedId);
    if (!selected) {
      setSelectedId(articles[0].id);
      setEditor(toEditorState(articles[0]));
      return;
    }
    setEditor((current) => {
      if (current.id !== selected.id) return current;
      return toEditorState(selected);
    });
  }, [articles, isCreatingNew, selectedId]);

  const saveMutation = useMutation({
    mutationFn: async ({ payload, forceCreate }: { payload: EditorState; forceCreate: boolean }) => {
      const body: KnowledgeBaseArticleUpsertPayload = {
        title: payload.title.trim(),
        request_type: payload.request_type,
        summary: payload.summary.trim(),
        content: payload.content.trim(),
        source_ticket_key: payload.source_ticket_key?.trim() || undefined,
      };
      if (forceCreate || !payload.id) {
        return api.createKnowledgeBaseArticle(body);
      }
      return api.updateKnowledgeBaseArticle(payload.id, body);
    },
    onSuccess: (article, variables) => {
      queryClient.invalidateQueries({ queryKey: ["kb-articles"] });
      setSelectedId(article.id);
      setIsCreatingNew(false);
      setEditor(toEditorState(article));
      setMessage({
        type: "info",
        text: variables.forceCreate
          ? `Created KB article ${article.title}.`
          : `Saved KB article ${article.title}.`,
      });
    },
    onError: (error) => {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : String(error),
      });
    },
  });

  const draftMutation = useMutation({
    mutationFn: ({ key, articleId }: { key: string; articleId?: number | null }) =>
      api.draftKnowledgeBaseArticleFromTicket(key, articleId),
    onSuccess: (draft) => {
      const target = draft.suggested_article_id
        ? articles.find((article) => article.id === draft.suggested_article_id)
        : null;
      setSelectedId(target?.id ?? null);
      setIsCreatingNew(!target);
      setEditor({
        id: target?.id ?? null,
        code: target?.code ?? "",
        title: draft.title,
        request_type: draft.request_type,
        summary: draft.summary,
        content: draft.content,
        source_ticket_key: draft.source_ticket_key,
        source_filename: target?.source_filename ?? "",
        imported_from_seed: target?.imported_from_seed ?? false,
        ai_generated: true,
      });
      setMessage({
        type: "info",
        text: draft.change_summary
          ? `${draft.recommended_action === "update_existing" ? "AI drafted an update" : "AI drafted a new article"}: ${draft.change_summary}`
          : `AI drafted ${draft.recommended_action === "update_existing" ? "an article update" : "a new article"} from ${draft.source_ticket_key}.`,
      });
    },
    onError: (error) => {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : String(error),
      });
    },
  });

  if (branding.scope !== "primary") {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-2xl font-bold text-slate-900">Knowledge Base</h1>
        <p className="mt-2 text-sm text-slate-500">
          The internal OIT knowledge base is only available on the primary site.
        </p>
      </div>
    );
  }

  const activeArticle = articles.find((article) => article.id === selectedId) ?? null;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Knowledge Base</h1>
          <p className="mt-1 text-sm text-slate-500">
            Browse and maintain internal OIT troubleshooting articles. AI triage also uses these articles as context.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => {
              setSelectedId(null);
              setIsCreatingNew(true);
              setEditor(emptyEditorState());
              setMessage(null);
            }}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
          >
            New Article
          </button>
          <button
            onClick={() => saveMutation.mutate({ payload: editor, forceCreate: false })}
            disabled={saveMutation.isPending || !editor.title.trim() || !editor.content.trim()}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saveMutation.isPending ? "Saving…" : editor.id ? "Save Changes" : "Create Article"}
          </button>
          {editor.id && (
            <button
              onClick={() => saveMutation.mutate({ payload: editor, forceCreate: true })}
              disabled={saveMutation.isPending || !editor.title.trim() || !editor.content.trim()}
              className="rounded-lg border border-blue-300 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 shadow-sm hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Save As New
            </button>
          )}
        </div>
      </div>

      {message && (
        <div className={`rounded-xl px-4 py-3 text-sm ${message.type === "error" ? "bg-red-50 text-red-700" : "bg-blue-50 text-blue-700"}`}>
          {message.text}
        </div>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end">
          <div className="flex-1">
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Search Articles</label>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search title, summary, steps, or code…"
              className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            />
          </div>
          <div className="w-full xl:w-80">
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Request Type</label>
            <select
              value={requestTypeFilter}
              onChange={(event) => setRequestTypeFilter(event.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            >
              <option value="">All request types</option>
              {requestTypes.map((option) => (
                <option key={option.id} value={option.name}>
                  {option.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 px-4 py-3">
            <div className="text-sm font-semibold text-slate-900">Articles</div>
            <div className="mt-1 text-xs text-slate-500">{articles.length} visible</div>
          </div>
          <div className="max-h-[72vh] overflow-y-auto">
            {isLoading && (
              <div className="px-4 py-8 text-center text-sm text-slate-400">Loading articles…</div>
            )}
            {!isLoading && articles.length === 0 && (
              <div className="px-4 py-8 text-center text-sm text-slate-400">No KB articles matched the current filters.</div>
            )}
            {articles.map((article) => (
              <button
                key={article.id}
                onClick={() => {
                  setSelectedId(article.id);
                  setIsCreatingNew(false);
                  setEditor(toEditorState(article));
                  setMessage(null);
                }}
                className={`block w-full border-b border-slate-100 px-4 py-3 text-left transition-colors ${selectedId === article.id ? "bg-blue-50" : "hover:bg-slate-50"}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      {article.code && (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-600">
                          {article.code}
                        </span>
                      )}
                      {article.imported_from_seed && (
                        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                          Seeded
                        </span>
                      )}
                      {article.ai_generated && (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                          AI
                        </span>
                      )}
                    </div>
                    <div className="mt-2 text-sm font-semibold text-slate-900">{article.title}</div>
                    <div className="mt-1 text-xs text-slate-500">{article.request_type || "General"}</div>
                    <p className="mt-2 text-xs leading-5 text-slate-600">{article.summary || article.content}</p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </section>

        <div className="space-y-5">
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">AI Draft From Closed Ticket</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Turn a resolved ticket into a KB draft. Review the output before saving it.
                </p>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  value={ticketKey}
                  onChange={(event) => setTicketKey(event.target.value.toUpperCase())}
                  placeholder="OIT-12345"
                  className="rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                />
                <button
                  onClick={() => draftMutation.mutate({ key: ticketKey.trim() })}
                  disabled={draftMutation.isPending || !ticketKey.trim()}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {draftMutation.isPending ? "Drafting…" : "Draft From Ticket"}
                </button>
                {editor.id && (
                  <button
                    onClick={() => draftMutation.mutate({ key: ticketKey.trim(), articleId: editor.id })}
                    disabled={draftMutation.isPending || !ticketKey.trim()}
                    className="rounded-lg border border-blue-300 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 shadow-sm hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Draft Update for Current Article
                  </button>
                )}
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">
                  {editor.id ? "Edit Article" : "New Article"}
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  {activeArticle
                    ? `Last updated ${formatTimestamp(activeArticle.updated_at)}`
                    : "Create a new internal troubleshooting article."}
                </p>
              </div>
              {activeArticle && (
                <div className="flex flex-wrap gap-2 text-xs">
                  {activeArticle.imported_from_seed && (
                    <span className="rounded-full bg-emerald-100 px-3 py-1 font-medium text-emerald-700">
                      Imported from DOCX
                    </span>
                  )}
                  {activeArticle.ai_generated && (
                    <span className="rounded-full bg-amber-100 px-3 py-1 font-medium text-amber-700">
                      AI-touched
                    </span>
                  )}
                  {activeArticle.source_ticket_key && (
                    <span className="rounded-full bg-slate-100 px-3 py-1 font-medium text-slate-600">
                      Ticket {activeArticle.source_ticket_key}
                    </span>
                  )}
                </div>
              )}
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Title</label>
                  <input
                    value={editor.title}
                    onChange={(event) => setEditor((current) => ({ ...current, title: event.target.value }))}
                    className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                  />
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Request Type</label>
                    <select
                      value={editor.request_type}
                      onChange={(event) => setEditor((current) => ({ ...current, request_type: event.target.value }))}
                      className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                    >
                      <option value="">General</option>
                      {requestTypes.map((option) => (
                        <option key={option.id} value={option.name}>
                          {option.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Source Ticket</label>
                    <input
                      value={editor.source_ticket_key ?? ""}
                      onChange={(event) => setEditor((current) => ({ ...current, source_ticket_key: event.target.value.toUpperCase() }))}
                      placeholder="Optional"
                      className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Summary</label>
                  <textarea
                    value={editor.summary}
                    onChange={(event) => setEditor((current) => ({ ...current, summary: event.target.value }))}
                    rows={3}
                    className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Article Content</label>
                  <textarea
                    value={editor.content}
                    onChange={(event) => setEditor((current) => ({ ...current, content: event.target.value }))}
                    rows={22}
                    className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-3 font-mono text-sm leading-6 text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                  />
                </div>
              </div>

              <aside className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <h3 className="text-sm font-semibold text-slate-900">Article Metadata</h3>
                <dl className="mt-4 space-y-3 text-sm">
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Code</dt>
                    <dd className="mt-1 text-slate-700">{editor.code || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Source File</dt>
                    <dd className="mt-1 break-all text-slate-700">{editor.source_filename || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Mode</dt>
                    <dd className="mt-1 text-slate-700">{editor.id ? "Update existing article" : "Create new article"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Imported Seed</dt>
                    <dd className="mt-1 text-slate-700">{editor.imported_from_seed ? "Yes" : "No"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">AI Drafted</dt>
                    <dd className="mt-1 text-slate-700">{editor.ai_generated ? "Yes" : "No"}</dd>
                  </div>
                </dl>
              </aside>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
