import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type AzureCostChatResponse } from "../lib/api.ts";

const starterPrompts = [
  "What are the highest-confidence savings opportunities right now?",
  "Which quick wins should we tackle first to save money in Azure?",
  "Where are we paying for idle or unattached resources right now?",
];

type CopilotTurn = {
  id: string;
  question: string;
  response: AzureCostChatResponse;
};

export default function AzureCopilotPage() {
  const [question, setQuestion] = useState("");
  const [model, setModel] = useState("");
  const [history, setHistory] = useState<CopilotTurn[]>([]);

  const { data: models = [] } = useQuery({
    queryKey: ["azure", "ai", "models"],
    queryFn: () => api.getAzureAIModels(),
    staleTime: 5 * 60 * 1000,
  });
  const statusQuery = useQuery({
    queryKey: ["azure", "status", "copilot-page"],
    queryFn: () => api.getAzureStatus(),
    staleTime: 30_000,
  });

  const askMutation = useMutation({
    mutationFn: () => api.askAzureCostCopilot(question, model || undefined),
    onSuccess: (response) => {
      setHistory((current) => [
        {
          id: `${response.generated_at}-${current.length}`,
          question,
          response,
        },
        ...current,
      ]);
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Azure Copilot</h1>
        <p className="mt-1 text-sm text-slate-500">
          Ask grounded cost and governance questions against the cached Azure dataset, using Ollama-backed local models and the ranked savings workspace.
        </p>
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid gap-3 md:grid-cols-[1fr,340px,auto]">
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            rows={5}
            placeholder={starterPrompts[0]}
            className="w-full rounded-xl border border-slate-300 px-3 py-3 text-sm outline-none transition focus:border-sky-500"
          />
          <select
            value={model}
            onChange={(event) => setModel(event.target.value)}
            className="rounded-xl border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="">Default Ollama model</option>
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
          {models.length} local model{models.length === 1 ? "" : "s"} available through Ollama
        </div>
      </section>

      {askMutation.isError && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {askMutation.error instanceof Error ? askMutation.error.message : "Failed to get a copilot answer"}
        </div>
      )}

      {history.length > 0 ? (
        <div className="space-y-4">
          {history.map((turn, index) => (
            <section key={turn.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-lg font-semibold text-slate-900">{index === 0 ? "Latest Answer" : "Earlier Answer"}</h2>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                  {turn.response.model_used}
                </span>
                <span className="text-xs text-slate-500">
                  {new Date(turn.response.generated_at).toLocaleString()}
                </span>
                {statusQuery.data?.last_refresh ? (
                  <span className="text-xs text-slate-500">
                    Azure cache refreshed {new Date(statusQuery.data.last_refresh).toLocaleString()}
                  </span>
                ) : null}
              </div>
              <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Question</div>
                <div className="mt-2 text-sm text-slate-800">{turn.question}</div>
              </div>
              <div className="mt-4 whitespace-pre-wrap rounded-xl bg-slate-50 px-4 py-4 text-sm leading-7 text-slate-800">
                {turn.response.answer}
              </div>
              <div className="mt-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Grounding Sources</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {turn.response.citations.map((citation) => (
                    <span key={`${turn.id}-${citation.source_type}-${citation.label}`} className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">
                      {citation.label}: {citation.detail}
                    </span>
                  ))}
                </div>
              </div>
            </section>
          ))}
        </div>
      ) : null}
    </div>
  );
}
