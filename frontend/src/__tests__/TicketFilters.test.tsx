import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, fireEvent, act } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import TicketFilters, { emptyFilters } from "../components/TicketFilters.tsx";
import type { TicketFilterValues } from "../components/TicketFilters.tsx";

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function renderFilters(
  overrides: Partial<TicketFilterValues> = {},
  onChange = vi.fn(),
) {
  const filters = { ...emptyFilters, ...overrides };
  return {
    onChange,
    ...render(
      <TicketFilters filters={filters} onFilterChange={onChange} />
    ),
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TicketFilters", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders all filter controls", () => {
    renderFilters();
    expect(screen.getByPlaceholderText("Search tickets...")).toBeInTheDocument();
    expect(screen.getByDisplayValue("All Statuses")).toBeInTheDocument();
    expect(screen.getByDisplayValue("All Priorities")).toBeInTheDocument();
    expect(screen.getByDisplayValue("All Types")).toBeInTheDocument();
    expect(screen.getByDisplayValue("All Tags")).toBeInTheDocument();
    expect(screen.getByText("Open Only")).toBeInTheDocument();
    expect(screen.getByText("Stale Only")).toBeInTheDocument();
  });

  it("debounces search input", () => {
    const { onChange } = renderFilters();
    const input = screen.getByPlaceholderText("Search tickets...");

    fireEvent.change(input, { target: { value: "test" } });
    // Not called yet (debounce)
    expect(onChange).not.toHaveBeenCalled();

    act(() => { vi.advanceTimersByTime(300); });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ search: "test" })
    );
  });

  it("fires callback on status change", () => {
    const { onChange } = renderFilters();
    const select = screen.getByDisplayValue("All Statuses");
    fireEvent.change(select, { target: { value: "Resolved" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ status: "Resolved" })
    );
  });

  it("fires callback on priority change", () => {
    const { onChange } = renderFilters();
    const select = screen.getByDisplayValue("All Priorities");
    fireEvent.change(select, { target: { value: "High" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ priority: "High" })
    );
  });

  it("fires callback on type change", () => {
    const { onChange } = renderFilters();
    const select = screen.getByDisplayValue("All Types");
    fireEvent.change(select, { target: { value: "[System] Change" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ issue_type: "[System] Change" })
    );
  });

  it("toggles open_only", () => {
    const { onChange } = renderFilters();
    fireEvent.click(screen.getByText("Open Only"));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ open_only: false })
    );
  });

  it("toggles stale_only", () => {
    const { onChange } = renderFilters();
    fireEvent.click(screen.getByText("Stale Only"));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ stale_only: true })
    );
  });

  it("shows clear button when filters active", () => {
    renderFilters({ status: "Open" });
    expect(screen.getByText("Clear Filters")).toBeInTheDocument();
  });

  it("clear button resets filters", () => {
    const { onChange } = renderFilters({ status: "Open" });
    fireEvent.click(screen.getByText("Clear Filters"));
    expect(onChange).toHaveBeenCalledWith(emptyFilters);
  });

  it("hides clear button when filters default", () => {
    renderFilters();
    expect(screen.queryByText("Clear Filters")).not.toBeInTheDocument();
  });
});
