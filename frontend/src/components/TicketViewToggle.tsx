export type TicketListView = "table" | "kanban";

interface TicketViewToggleProps {
  value: TicketListView;
  onChange: (view: TicketListView) => void;
}

const baseClass =
  "inline-flex items-center rounded-md px-3 py-1.5 text-sm font-medium transition-colors";

export default function TicketViewToggle({ value, onChange }: TicketViewToggleProps) {
  return (
    <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1 shadow-sm">
      <button
        type="button"
        aria-pressed={value === "table"}
        onClick={() => onChange("table")}
        className={[
          baseClass,
          value === "table" ? "bg-slate-900 text-white" : "text-gray-600 hover:bg-gray-100",
        ].join(" ")}
      >
        Table
      </button>
      <button
        type="button"
        aria-pressed={value === "kanban"}
        onClick={() => onChange("kanban")}
        className={[
          baseClass,
          value === "kanban" ? "bg-slate-900 text-white" : "text-gray-600 hover:bg-gray-100",
        ].join(" ")}
      >
        Kanban
      </button>
    </div>
  );
}
