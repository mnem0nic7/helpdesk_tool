import { useState } from "react";
import { api } from "../lib/api.ts";

// ---------------------------------------------------------------------------
// Icons (inline SVG to avoid extra dependencies)
// ---------------------------------------------------------------------------

function DownloadIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={2}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
      />
    </svg>
  );
}

function SpreadsheetIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={1.5}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0112 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m17.25-3.75h-7.5c-.621 0-1.125.504-1.125 1.125m8.625-1.125c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-17.25 0h7.5m-7.5 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125M12 10.875v-1.5m0 1.5c0 .621-.504 1.125-1.125 1.125M12 10.875c0 .621.504 1.125 1.125 1.125m-2.25 0c.621 0 1.125.504 1.125 1.125M10.875 12c-.621 0-1.125.504-1.125 1.125M12 12c.621 0 1.125.504 1.125 1.125m-2.25 0c.621 0 1.125.504 1.125 1.125m0 0v1.5c0 .621-.504 1.125-1.125 1.125M12 15.375c0-.621.504-1.125 1.125-1.125"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Column list for the "What's included" section
// ---------------------------------------------------------------------------

const EXPORT_COLUMNS = [
  { name: "Key", description: "Jira issue key (e.g. OIT-1234)" },
  { name: "Summary", description: "Issue title / summary" },
  { name: "Type", description: "Issue type (e.g. Service Request, Incident)" },
  { name: "Status", description: "Current workflow status" },
  { name: "Priority", description: "Priority level (Highest to Lowest)" },
  { name: "Assignee", description: "Currently assigned team member" },
  { name: "Reporter", description: "Person who created the ticket" },
  { name: "Created / Updated / Resolved", description: "Key date timestamps" },
  { name: "TTR (hours)", description: "Time-to-resolution in hours" },
  { name: "Age (days)", description: "Age of open tickets in days" },
  { name: "SLA Response", description: "First-response SLA status (Met / Breached / Running)" },
  { name: "SLA Resolution", description: "Resolution SLA status (Met / Breached / Running)" },
  { name: "Excluded", description: "Whether the ticket is flagged for exclusion from metrics" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ReportsPage() {
  const [downloading, setDownloading] = useState(false);

  function handleExport() {
    setDownloading(true);
    // Open the export URL in a new tab -- this triggers the browser download
    window.open(api.exportExcel(), "_blank");
    // Reset the button state after a short delay (the actual download
    // is handled by the browser so we can't track it precisely)
    setTimeout(() => setDownloading(false), 3000);
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Reports</h1>
        <p className="mt-2 text-gray-500">
          Export helpdesk data to Excel for offline analysis, auditing, or
          sharing with stakeholders.
        </p>
      </div>

      {/* Main export card */}
      <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
        <div className="p-6 sm:p-8">
          <div className="flex items-start gap-5">
            {/* Icon */}
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-blue-50">
              <SpreadsheetIcon className="h-6 w-6 text-blue-600" />
            </div>

            {/* Content */}
            <div className="flex-1 space-y-4">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">
                  Full Ticket Export
                </h2>
                <p className="mt-1 text-sm text-gray-500">
                  Download a complete Excel workbook containing every OIT
                  helpdesk ticket with exclusion flags, SLA statuses, and
                  computed metrics. The file includes auto-filters and a frozen
                  header row for easy analysis.
                </p>
              </div>

              {/* Export button */}
              <button
                onClick={handleExport}
                disabled={downloading}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {downloading ? (
                  <>
                    <svg
                      className="h-5 w-5 animate-spin"
                      xmlns="http://www.w3.org/2000/svg"
                      fill="none"
                      viewBox="0 0 24 24"
                    >
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                      />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                      />
                    </svg>
                    Generating Report...
                  </>
                ) : (
                  <>
                    <DownloadIcon className="h-5 w-5" />
                    Export All Tickets to Excel
                  </>
                )}
              </button>

              <p className="text-xs text-gray-400">
                The export may take a moment while all tickets are fetched from
                Jira. The file will open in a new tab.
              </p>
            </div>
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-gray-200" />

        {/* What's included */}
        <div className="p-6 sm:p-8">
          <h3 className="text-sm font-semibold text-gray-900">
            Columns Included
          </h3>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {EXPORT_COLUMNS.map((col) => (
              <div key={col.name} className="flex items-start gap-2">
                <span className="mt-0.5 block h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" />
                <div>
                  <span className="text-sm font-medium text-gray-700">
                    {col.name}
                  </span>
                  <span className="text-sm text-gray-400"> -- {col.description}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Notes section */}
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-5">
        <h3 className="text-sm font-semibold text-amber-800">Notes</h3>
        <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-amber-700">
          <li>
            The export includes <strong>all</strong> OIT project tickets,
            including those flagged as excluded (oasisdev). Use the
            &quot;Excluded&quot; column to filter them out in Excel if needed.
          </li>
          <li>
            SLA status values: <strong>Met</strong>, <strong>BREACHED</strong>,{" "}
            <strong>Running</strong>, <strong>Paused</strong>, or empty if no
            SLA timer applies.
          </li>
          <li>
            TTR (Time to Resolution) is computed as calendar hours from ticket
            creation to resolution.
          </li>
        </ul>
      </div>
    </div>
  );
}
