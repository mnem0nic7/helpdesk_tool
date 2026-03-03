import type { SLATimerSummary } from "../lib/api.ts";

interface SLAComplianceCardProps {
  timer: SLATimerSummary;
}

export default function SLAComplianceCard({ timer }: SLAComplianceCardProps) {
  const { timer_name, total, met, breached, running, paused, met_rate, breach_rate } = timer;

  // Calculate percentages for the stacked bar
  const metPct = total > 0 ? (met / total) * 100 : 0;
  const breachedPct = total > 0 ? (breached / total) * 100 : 0;
  const runningPct = total > 0 ? (running / total) * 100 : 0;
  const pausedPct = total > 0 ? (paused / total) * 100 : 0;

  return (
    <div className="rounded-lg bg-white px-5 py-5 shadow">
      {/* Timer name */}
      <h3 className="text-sm font-semibold tracking-wide text-gray-700 uppercase">
        {timer_name}
      </h3>

      {/* Large percentage numbers */}
      <div className="mt-3 flex items-baseline gap-4">
        <div>
          <span className="text-3xl font-bold text-green-600">
            {met_rate.toFixed(1)}%
          </span>
          <span className="ml-1 text-xs text-gray-500">Met</span>
        </div>
        <div>
          <span className="text-3xl font-bold text-red-600">
            {breach_rate.toFixed(1)}%
          </span>
          <span className="ml-1 text-xs text-gray-500">Breached</span>
        </div>
      </div>

      {/* Stacked horizontal bar */}
      <div className="mt-4 flex h-4 w-full overflow-hidden rounded-full bg-gray-100">
        {metPct > 0 && (
          <div
            className="bg-green-500 transition-all"
            style={{ width: `${metPct}%` }}
            title={`Met: ${met} (${metPct.toFixed(1)}%)`}
          />
        )}
        {runningPct > 0 && (
          <div
            className="bg-blue-500 transition-all"
            style={{ width: `${runningPct}%` }}
            title={`Running: ${running} (${runningPct.toFixed(1)}%)`}
          />
        )}
        {pausedPct > 0 && (
          <div
            className="bg-yellow-400 transition-all"
            style={{ width: `${pausedPct}%` }}
            title={`Paused: ${paused} (${pausedPct.toFixed(1)}%)`}
          />
        )}
        {breachedPct > 0 && (
          <div
            className="bg-red-500 transition-all"
            style={{ width: `${breachedPct}%` }}
            title={`Breached: ${breached} (${breachedPct.toFixed(1)}%)`}
          />
        )}
      </div>

      {/* Legend with counts */}
      <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-600">
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-green-500" />
          Met: {met}
        </span>
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-red-500" />
          Breached: {breached}
        </span>
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-blue-500" />
          Running: {running}
        </span>
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-yellow-400" />
          Paused: {paused}
        </span>
      </div>
    </div>
  );
}
