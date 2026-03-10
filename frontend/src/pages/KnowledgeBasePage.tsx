import { useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type {
  KnowledgeBaseArticle,
  KnowledgeBaseArticleUpsertPayload,
} from "../lib/api.ts";
import { getSiteBranding } from "../lib/siteContext.ts";

type Mode = "view" | "edit" | "create";

type EditorState = KnowledgeBaseArticleUpsertPayload & {
  id: number | null;
  code: string;
  source_filename: string;
  imported_from_seed: boolean;
  ai_generated: boolean;
};

function toEditorState(article: KnowledgeBaseArticle): EditorState {
  return {
    id: article.id ?? null,
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

// ---------------------------------------------------------------------------
// Lightweight markdown renderer — handles DOCX plain text and AI markdown
// ---------------------------------------------------------------------------

type CalloutStyle = {
  border: string;
  bg: string;
  label: string;
  labelColor: string;
};

const CALLOUT_STYLES: Record<string, CalloutStyle> = {
  note:      { border: "border-blue-300",  bg: "bg-blue-50",  label: "Note",      labelColor: "text-blue-700" },
  fyi:       { border: "border-blue-300",  bg: "bg-blue-50",  label: "FYI",       labelColor: "text-blue-700" },
  tip:       { border: "border-green-300", bg: "bg-green-50", label: "Tip",       labelColor: "text-green-700" },
  warning:   { border: "border-amber-300", bg: "bg-amber-50", label: "Warning",   labelColor: "text-amber-700" },
  caution:   { border: "border-amber-300", bg: "bg-amber-50", label: "Caution",   labelColor: "text-amber-700" },
  important: { border: "border-red-300",   bg: "bg-red-50",   label: "Important", labelColor: "text-red-700" },
  critical:  { border: "border-red-300",   bg: "bg-red-50",   label: "Critical",  labelColor: "text-red-700" },
};

function getCallout(text: string): { style: CalloutStyle; body: string } | null {
  const m = text.match(/^(note|fyi|tip|warning|caution|important|critical):\s*/i);
  if (!m) return null;
  const style = CALLOUT_STYLES[m[1].toLowerCase()];
  return style ? { style, body: text.slice(m[0].length) } : null;
}

function renderInline(text: string) {
  const parts: ReactNode[] = [];
  const re = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    if (m[0].startsWith("**")) {
      parts.push(<strong key={m.index}>{m[2]}</strong>);
    } else if (m[0].startsWith("*")) {
      parts.push(<em key={m.index}>{m[3]}</em>);
    } else {
      parts.push(
        <code key={m.index} className="rounded bg-slate-100 px-1 font-mono text-xs text-slate-700">
          {m[4]}
        </code>,
      );
    }
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts.length === 1 && typeof parts[0] === "string" ? parts[0] : <>{parts}</>;
}

function ArticleContent({ text }: { text: string }) {
  if (!text) return <p className="italic text-slate-400">No content.</p>;

  const blocks = text.split(/\n\n+/);
  return (
    <div className="space-y-4 text-[15px] leading-relaxed text-slate-800">
      {blocks.map((block, i) => {
        const trimmed = block.trim();
        if (!trimmed) return null;

        // Horizontal rule
        if (/^(-{3,}|\*{3,})$/.test(trimmed))
          return <hr key={i} className="border-slate-200" />;

        // Fenced code block
        if (trimmed.startsWith("```")) {
          const inner = trimmed.replace(/^```\w*\n?/, "").replace(/\n?```$/, "");
          return (
            <pre key={i} className="overflow-x-auto rounded-lg bg-slate-900 p-4 font-mono text-xs leading-5 text-slate-100">
              {inner}
            </pre>
          );
        }

        // Headings
        if (trimmed.startsWith("### "))
          return (
            <h4 key={i} className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              {trimmed.slice(4)}
            </h4>
          );
        if (trimmed.startsWith("## "))
          return (
            <h3 key={i} className="border-b border-slate-200 pb-1 text-base font-semibold text-slate-900">
              {trimmed.slice(3)}
            </h3>
          );
        if (trimmed.startsWith("# "))
          return (
            <h2 key={i} className="text-lg font-bold text-slate-900">
              {trimmed.slice(2)}
            </h2>
          );

        const lines = trimmed.split("\n").filter((l) => l.trim());

        // Unordered list
        if (lines.length > 0 && lines.every((l) => /^[-*•]\s/.test(l))) {
          return (
            <ul key={i} className="space-y-1.5 pl-1">
              {lines.map((l, j) => (
                <li key={j} className="flex gap-2.5">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-400" />
                  <span>{renderInline(l.replace(/^[-*•]\s+/, ""))}</span>
                </li>
              ))}
            </ul>
          );
        }

        // Ordered list — rendered as numbered step cards
        if (lines.length > 0 && lines.every((l) => /^\d+[.)]\s/.test(l))) {
          return (
            <div key={i} className="space-y-2">
              {lines.map((l, j) => (
                <div key={j} className="flex gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-700 text-xs font-bold text-white">
                    {j + 1}
                  </span>
                  <span className="flex-1 pt-0.5">{renderInline(l.replace(/^\d+[.)]\s+/, ""))}</span>
                </div>
              ))}
            </div>
          );
        }

        // Callout box — Note / Tip / Warning / Important / etc.
        const callout = getCallout(trimmed);
        if (callout) {
          return (
            <div
              key={i}
              className={`rounded-lg border-l-4 px-4 py-3 ${callout.style.border} ${callout.style.bg}`}
            >
              <span className={`mr-2 text-xs font-bold uppercase tracking-wide ${callout.style.labelColor}`}>
                {callout.style.label}
              </span>
              <span className="text-sm text-slate-700">{renderInline(callout.body)}</span>
            </div>
          );
        }

        // Regular paragraph
        return (
          <p key={i}>
            {trimmed.split("\n").map((l, j) => (
              <span key={j}>
                {j > 0 && <br />}
                {renderInline(l)}
              </span>
            ))}
          </p>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function KnowledgeBasePage() {
  const branding = getSiteBranding();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState("");
  const [requestTypeFilter, setRequestTypeFilter] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>("view");
  const [editor, setEditor] = useState<EditorState>(emptyEditorState());
  const [ticketKey, setTicketKey] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmReformatAll, setConfirmReformatAll] = useState(false);
  const [sopFile, setSopFile] = useState<File | null>(null);
  const sopInputRef = useRef<HTMLInputElement>(null);
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
      if (mode !== "create") {
        setSelectedId(null);
        setEditor((prev) => (prev.id === null ? prev : emptyEditorState()));
      }
      return;
    }
    if (mode === "create") return;
    const selected = articles.find((a) => a.id === selectedId);
    if (!selected) {
      setSelectedId(articles[0].id ?? null);
      setEditor(toEditorState(articles[0]));
      setMode("view");
      return;
    }
    if (mode === "view") {
      setEditor((prev) => (prev.id !== (selected.id ?? null) ? prev : toEditorState(selected)));
    }
  }, [articles, mode, selectedId]);

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
      setSelectedId(article.id ?? null);
      setMode("view");
      setEditor(toEditorState(article));
      setConfirmDelete(false);
      setMessage({
        type: "info",
        text: variables.forceCreate ? `Created "${article.title}".` : `Saved "${article.title}".`,
      });
    },
    onError: (error) => {
      setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteKnowledgeBaseArticle(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kb-articles"] });
      setSelectedId(null);
      setMode("view");
      setEditor(emptyEditorState());
      setConfirmDelete(false);
      setMessage({ type: "info", text: "Article deleted." });
    },
    onError: (error) => {
      setConfirmDelete(false);
      setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const reformatMutation = useMutation({
    mutationFn: (id: number) => api.reformatKnowledgeBaseArticle(id),
    onSuccess: (result) => {
      setMode("edit");
      setEditor((s) => ({ ...s, content: result.content }));
      setMessage({ type: "info", text: "AI reformatted the content. Review and save to apply." });
    },
    onError: (error) => {
      setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const reformatAllMutation = useMutation({
    mutationFn: () => api.reformatAllKnowledgeBaseArticles(),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["kb-articles"] });
      setConfirmReformatAll(false);
      setMessage({ type: "info", text: `Reformatted ${result.reformatted} article${result.reformatted !== 1 ? "s" : ""}.` });
    },
    onError: (error) => {
      setConfirmReformatAll(false);
      setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const sopMutation = useMutation({
    mutationFn: (file: File) => api.draftKBArticleFromSOP(file),
    onSuccess: (draft) => {
      setSelectedId(null);
      setMode("create");
      setEditor({
        id: null,
        code: "",
        title: draft.title,
        request_type: draft.request_type,
        summary: draft.summary,
        content: draft.content,
        source_ticket_key: "",
        source_filename: "",
        imported_from_seed: false,
        ai_generated: true,
      });
      setSopFile(null);
      if (sopInputRef.current) sopInputRef.current.value = "";
      setMessage({ type: "info", text: `AI converted the SOP to a draft. Review and save.` });
    },
    onError: (error) => {
      setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const draftMutation = useMutation({
    mutationFn: ({ key, articleId }: { key: string; articleId?: number | null }) =>
      api.draftKnowledgeBaseArticleFromTicket(key, articleId),
    onSuccess: (draft) => {
      const target = draft.suggested_article_id
        ? articles.find((a) => a.id === draft.suggested_article_id)
        : null;
      setSelectedId(target?.id ?? null);
      setMode(target ? "edit" : "create");
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
          : `AI drafted ${draft.recommended_action === "update_existing" ? "an update" : "a new article"} from ${draft.source_ticket_key}.`,
      });
    },
    onError: (error) => {
      setMessage({ type: "error", text: error instanceof Error ? error.message : String(error) });
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

  const activeArticle = articles.find((a) => a.id === selectedId) ?? null;

  function handleSelectArticle(article: KnowledgeBaseArticle) {
    setSelectedId(article.id ?? null);
    setMode("view");
    setEditor(toEditorState(article));
    setConfirmDelete(false);
    setMessage(null);
  }

  function handleNewArticle() {
    setSelectedId(null);
    setMode("create");
    setEditor(emptyEditorState());
    setConfirmDelete(false);
    setMessage(null);
  }

  function handleCancelEdit() {
    if (activeArticle) {
      setMode("view");
      setEditor(toEditorState(activeArticle));
    } else {
      setMode("view");
      setEditor(emptyEditorState());
    }
    setConfirmDelete(false);
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Knowledge Base</h1>
          <p className="mt-1 text-sm text-slate-500">
            Internal OIT troubleshooting articles — also used as context for AI triage.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {confirmReformatAll ? (
            <>
              <span className="self-center text-xs text-amber-700">
                Reformat all 147 articles with AI?
              </span>
              <button
                onClick={() => reformatAllMutation.mutate()}
                disabled={reformatAllMutation.isPending}
                className="self-start rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-amber-700 disabled:opacity-50"
              >
                {reformatAllMutation.isPending ? "Reformatting…" : "Confirm"}
              </button>
              <button
                onClick={() => setConfirmReformatAll(false)}
                className="self-start rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-600 shadow-sm hover:bg-slate-50"
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              onClick={() => setConfirmReformatAll(true)}
              className="self-start rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-700 shadow-sm hover:bg-amber-100"
            >
              Reformat All
            </button>
          )}
          <button
            onClick={handleNewArticle}
            className="self-start rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
          >
            + New Article
          </button>
        </div>
      </div>

      {message && (
        <div
          className={`rounded-xl px-4 py-3 text-sm ${
            message.type === "error" ? "bg-red-50 text-red-700" : "bg-blue-50 text-blue-700"
          }`}
        >
          {message.text}
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
        {/* Left: search + article list */}
        <aside className="space-y-3">
          <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search articles…"
              className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            />
            <select
              value={requestTypeFilter}
              onChange={(e) => setRequestTypeFilter(e.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            >
              <option value="">All request types</option>
              {requestTypes.map((rt) => (
                <option key={rt.id} value={rt.name}>
                  {rt.name}
                </option>
              ))}
            </select>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
              <span className="text-sm font-semibold text-slate-900">Articles</span>
              <span className="text-xs text-slate-400">{articles.length}</span>
            </div>
            <div className="max-h-[66vh] overflow-y-auto">
              {isLoading && (
                <div className="px-4 py-6 text-center text-sm text-slate-400">Loading…</div>
              )}
              {!isLoading && articles.length === 0 && (
                <div className="px-4 py-6 text-center text-sm text-slate-400">No articles found.</div>
              )}
              {articles.map((article) => (
                <button
                  key={article.id}
                  onClick={() => handleSelectArticle(article)}
                  className={`block w-full border-b border-slate-100 px-4 py-3 text-left transition-colors last:border-0 ${
                    selectedId === article.id && mode !== "create" ? "bg-blue-50" : "hover:bg-slate-50"
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    {article.code && (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-600">
                        {article.code}
                      </span>
                    )}
                    {article.imported_from_seed && (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                        Seeded
                      </span>
                    )}
                    {article.ai_generated && (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                        AI
                      </span>
                    )}
                  </div>
                  <div className="mt-1.5 text-sm font-medium leading-snug text-slate-900">
                    {article.title}
                  </div>
                  <div className="mt-0.5 text-xs text-slate-400">
                    {article.request_type || "General"}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </aside>

        {/* Right: AI draft panel + content panel */}
        <div className="space-y-4">
          {/* AI Draft — always visible */}
          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Draft From Closed Ticket</h2>
                <p className="mt-0.5 text-xs text-slate-500">
                  Generate a new article or update using a resolved ticket as source.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <input
                  value={ticketKey}
                  onChange={(e) => setTicketKey(e.target.value.toUpperCase())}
                  placeholder="OIT-12345"
                  className="w-32 rounded-xl border border-slate-300 px-3 py-1.5 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                />
                <button
                  onClick={() => draftMutation.mutate({ key: ticketKey.trim() })}
                  disabled={draftMutation.isPending || !ticketKey.trim()}
                  className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {draftMutation.isPending ? "Drafting…" : "Draft From Ticket"}
                </button>
                {activeArticle && mode === "view" && (
                  <button
                    onClick={() =>
                      draftMutation.mutate({ key: ticketKey.trim(), articleId: activeArticle.id })
                    }
                    disabled={draftMutation.isPending || !ticketKey.trim()}
                    className="rounded-lg border border-blue-300 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700 shadow-sm hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Draft Update for This Article
                  </button>
                )}
              </div>
            </div>

            {/* SOP upload */}
            <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-3">
              <div>
                <span className="text-sm font-semibold text-slate-900">Upload SOP</span>
                <span className="ml-2 text-xs text-slate-400">.docx · .pdf · .txt</span>
              </div>
              <input
                ref={sopInputRef}
                type="file"
                accept=".docx,.pdf,.txt"
                onChange={(e) => setSopFile(e.target.files?.[0] ?? null)}
                className="text-xs text-slate-600 file:mr-2 file:cursor-pointer file:rounded-lg file:border file:border-slate-300 file:bg-white file:px-3 file:py-1 file:text-xs file:font-medium file:text-slate-700 file:hover:bg-slate-50"
              />
              <button
                onClick={() => sopFile && sopMutation.mutate(sopFile)}
                disabled={sopMutation.isPending || !sopFile}
                className="rounded-lg bg-slate-700 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {sopMutation.isPending ? "Converting…" : "Convert to Article"}
              </button>
            </div>
          </section>

          {/* Empty state */}
          {mode === "view" && !activeArticle && (
            <div className="flex items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 py-24">
              <p className="text-sm text-slate-400">
                Select an article to read it, or{" "}
                <button
                  onClick={handleNewArticle}
                  className="font-medium text-blue-600 hover:underline"
                >
                  create a new one
                </button>
                .
              </p>
            </div>
          )}

          {/* View mode */}
          {mode === "view" && activeArticle && (
            <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    {activeArticle.code && (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-600">
                        {activeArticle.code}
                      </span>
                    )}
                    {activeArticle.imported_from_seed && (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
                        Imported from DOCX
                      </span>
                    )}
                    {activeArticle.ai_generated && (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                        AI-touched
                      </span>
                    )}
                    {activeArticle.source_ticket_key && (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                        {activeArticle.source_ticket_key}
                      </span>
                    )}
                  </div>
                  <h2 className="mt-2 text-xl font-bold text-slate-900">{activeArticle.title}</h2>
                  <p className="mt-1 text-xs text-slate-400">
                    {activeArticle.request_type || "General"} · Updated{" "}
                    {formatTimestamp(activeArticle.updated_at)}
                  </p>
                </div>

                <div className="flex shrink-0 items-center gap-2">
                  {confirmDelete ? (
                    <>
                      <span className="text-xs text-red-600">Delete this article?</span>
                      <button
                        onClick={() => activeArticle.id && deleteMutation.mutate(activeArticle.id)}
                        disabled={deleteMutation.isPending}
                        className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                      >
                        {deleteMutation.isPending ? "Deleting…" : "Confirm Delete"}
                      </button>
                      <button
                        onClick={() => setConfirmDelete(false)}
                        className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => setMode("edit")}
                        className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => activeArticle.id && reformatMutation.mutate(activeArticle.id)}
                        disabled={reformatMutation.isPending}
                        className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 shadow-sm hover:bg-amber-100 disabled:opacity-50"
                      >
                        {reformatMutation.isPending ? "Reformatting…" : "Reformat with AI"}
                      </button>
                      <button
                        onClick={() => setConfirmDelete(true)}
                        className="rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-medium text-red-600 shadow-sm hover:bg-red-50"
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </div>

              {activeArticle.summary && activeArticle.summary !== activeArticle.content && (
                <p className="mt-4 text-sm italic text-slate-500">{activeArticle.summary}</p>
              )}

              <div className="mt-4">
                <ArticleContent text={activeArticle.content} />
              </div>
            </section>
          )}

          {/* Edit / Create mode */}
          {(mode === "edit" || mode === "create") && (
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between border-b border-slate-200 pb-4">
                <h2 className="text-lg font-semibold text-slate-900">
                  {mode === "create" ? "New Article" : "Edit Article"}
                </h2>
                <div className="flex gap-2">
                  <button
                    onClick={handleCancelEdit}
                    className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
                  >
                    Cancel
                  </button>
                  {mode === "edit" && editor.id && (
                    <button
                      onClick={() => saveMutation.mutate({ payload: editor, forceCreate: true })}
                      disabled={saveMutation.isPending || !editor.title.trim() || !editor.content.trim()}
                      className="rounded-lg border border-blue-300 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Save As New
                    </button>
                  )}
                  <button
                    onClick={() => saveMutation.mutate({ payload: editor, forceCreate: false })}
                    disabled={saveMutation.isPending || !editor.title.trim() || !editor.content.trim()}
                    className="rounded-lg bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {saveMutation.isPending
                      ? "Saving…"
                      : mode === "create"
                        ? "Create Article"
                        : "Save Changes"}
                  </button>
                </div>
              </div>

              <div className="mt-5 space-y-4">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Title
                  </label>
                  <input
                    value={editor.title}
                    onChange={(e) => setEditor((s) => ({ ...s, title: e.target.value }))}
                    className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                  />
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Request Type
                    </label>
                    <select
                      value={editor.request_type}
                      onChange={(e) => setEditor((s) => ({ ...s, request_type: e.target.value }))}
                      className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                    >
                      <option value="">General</option>
                      {requestTypes.map((rt) => (
                        <option key={rt.id} value={rt.name}>
                          {rt.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Source Ticket
                    </label>
                    <input
                      value={editor.source_ticket_key ?? ""}
                      onChange={(e) =>
                        setEditor((s) => ({ ...s, source_ticket_key: e.target.value.toUpperCase() }))
                      }
                      placeholder="Optional"
                      className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Summary
                  </label>
                  <textarea
                    value={editor.summary}
                    onChange={(e) => setEditor((s) => ({ ...s, summary: e.target.value }))}
                    rows={2}
                    className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Content
                  </label>
                  <textarea
                    value={editor.content}
                    onChange={(e) => setEditor((s) => ({ ...s, content: e.target.value }))}
                    rows={24}
                    className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-3 font-mono text-sm leading-6 text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                  />
                </div>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
