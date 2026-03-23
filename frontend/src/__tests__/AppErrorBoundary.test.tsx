import { describe, expect, it, vi, afterEach } from "vitest"
import { render, screen } from "@testing-library/react"
import type { ReactElement } from "react"
import AppErrorBoundary from "../components/AppErrorBoundary"

const logClientError = vi.fn()

vi.mock("../lib/errorLogging", () => ({
  logClientError,
}))

afterEach(() => {
  vi.clearAllMocks()
})

function ThrowingChild(): ReactElement {
  throw new Error("render failed")
}

describe("AppErrorBoundary", () => {
  it("logs render errors and shows the fallback UI", () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined)

    render(
      <AppErrorBoundary>
        <ThrowingChild />
      </AppErrorBoundary>
    )

    expect(screen.getByText("Something went wrong")).toBeInTheDocument()
    expect(screen.getByText(/The error has been logged/i)).toBeInTheDocument()
    expect(logClientError).toHaveBeenCalledTimes(1)
    expect(logClientError.mock.calls[0][0]).toBe("React render error")
    consoleErrorSpy.mockRestore()
  })
})
