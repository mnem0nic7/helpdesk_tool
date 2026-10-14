import { Link } from "react-router-dom";

export default function HrAppPage() {
  return (
    <div className="mx-auto max-w-3xl p-6">
      <h1 className="text-2xl font-semibold text-slate-900">AskHR Portal</h1>
      <p className="mt-1 text-sm text-slate-500">HR and Benefits automation tools.</p>

      <div className="mt-6 grid gap-4">
        <Link
          to="/askhr-bot"
          className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm transition hover:border-slate-300 hover:shadow"
        >
          <h2 className="text-lg font-semibold text-slate-900">AskHR / Benefits Bot</h2>
          <p className="mt-1 text-sm text-slate-500">
            Status, run history, and retry for the mailbox-to-Jira ticket bot.
          </p>
        </Link>
        <Link
          to="/entra-sync"
          className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm transition hover:border-slate-300 hover:shadow"
        >
          <h2 className="text-lg font-semibold text-slate-900">Entra → Jira Sync</h2>
          <p className="mt-1 text-sm text-slate-500">
            Status, field mapping, and per-ticket results for the connector that fills HRD and LIBTA tickets from Entra.
          </p>
        </Link>
      </div>
    </div>
  );
}
