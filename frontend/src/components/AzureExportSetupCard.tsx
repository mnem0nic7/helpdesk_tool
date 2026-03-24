import { Link } from "react-router-dom";

export default function AzureExportSetupCard({
  title = "Enable Cost Exports",
  body,
  compact = false,
}: {
  title?: string;
  body?: string;
  compact?: boolean;
}) {
  return (
    <section
      className={[
        "rounded-2xl border border-amber-200 bg-amber-50 text-amber-950 shadow-sm",
        compact ? "p-4" : "p-5",
      ].join(" ")}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl">
          <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Export-backed reporting dependency</div>
          <h2 className="mt-2 text-lg font-semibold text-amber-950">{title}</h2>
          <p className="mt-2 text-sm leading-6 text-amber-900">
            {body ||
              "Cost exports are still disabled, so governed reporting, FinOps validation signoff, and allocation runs stay in a waiting state. Turn on the Azure Cost Management export lane first, then these sections will unlock automatically."}
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs font-medium text-amber-800">
            <span className="rounded-full bg-white/80 px-3 py-1">Unlocks governed reporting</span>
            <span className="rounded-full bg-white/80 px-3 py-1">Enables FinOps validation</span>
            <span className="rounded-full bg-white/80 px-3 py-1">Activates allocation runs</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            to="/cost"
            className="rounded-xl bg-amber-700 px-4 py-2 text-sm font-medium text-white transition hover:bg-amber-800"
          >
            Open Cost Setup Guide
          </Link>
          <Link
            to="/"
            className="rounded-xl border border-amber-300 bg-white px-4 py-2 text-sm font-medium text-amber-900 transition hover:bg-amber-100"
          >
            Review Overview
          </Link>
        </div>
      </div>
    </section>
  );
}
