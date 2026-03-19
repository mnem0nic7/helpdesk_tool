import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";

const starterPrompts = [
  "What are the highest-confidence savings opportunities right now?",
  "Which quick wins should we tackle first to save money in Azure?",
  "Where are we paying for idle or unattached resources right now?",
];

export default function AzureCopilotPage() {
  const [question, setQuestion] = useState(starterPrompts[0]);
  const [model, setModel] = useState("");

  const { data: models = [] } = useQuery({
    queryKey: ["azure", "ai", "models"],
    queryFn: () => api.getAzureAIModels(),
    staleTime: 5 * 60 * 1000,
  });

  const askMutation = useMutation({
    mutationFn: () => api.askAzureCostCopilot(question, model || undefined),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Azure Copilot</h1>
        <p className="mt-1 text-sm text-slate-500">
          Ask grounded cost and governance questions against the cached Azure dataset, including the new ranked savings workspace.
        </p>
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid gap-3 md:grid-cols-[1fr,340px,auto]">
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            rows={5}
            className="w-full rounded-xl border border-slate-300 px-3 py-3 text-sm outline-none transition focus:border-sky-500"
          />
          <select
            value={model}
            onChange={(event) => setModel(event.target.value)}
            className="rounded-xl border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="">Default model</option>
            {models.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name === item.id ? item.id : `${item.name} (${item.id})`}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => askMutation.mutate()}
            disabled={askMutation.isPending || !question.trim()}
            className="rounded-xl bg-sky-700 px-5 py-2 text-sm font-medium text-white transition hover:bg-sky-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {askMutation.isPending ? "Thinking..." : "Ask Copilot"}
          </button>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {starterPrompts.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => setQuestion(prompt)}
              className="rounded-full border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              {prompt}
            </button>
          ))}
        </div>

        <div className="mt-3 text-xs text-slate-500">
          {models.length} model{models.length === 1 ? "" : "s"} available
        </div>
      </section>

      {askMutation.isError && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {askMutation.error instanceof Error ? askMutation.error.message : "Failed to get a copilot answer"}
        </div>
      )}

      {askMutation.data && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold text-slate-900">Latest Answer</h2>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
              {askMutation.data.model_used}
            </span>
            <span className="text-xs text-slate-500">
              {new Date(askMutation.data.generated_at).toLocaleString()}
            </span>
          </div>
          <div className="mt-4 whitespace-pre-wrap rounded-xl bg-slate-50 px-4 py-4 text-sm leading-7 text-slate-800">
            {askMutation.data.answer}
          </div>
          <div className="mt-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Grounding Sources</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {askMutation.data.citations.map((citation) => (
                <span key={`${citation.source_type}-${citation.label}`} className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">
                  {citation.label}: {citation.detail}
                </span>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
