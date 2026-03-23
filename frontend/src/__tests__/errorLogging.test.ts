import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installGlobalErrorLogging, logClientError } from "../lib/errorLogging"

describe("error logging", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("logs structured client errors", () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined)
    const error = new Error("boom")

    logClientError("Test error", error, { scope: "unit" })

    expect(consoleErrorSpy).toHaveBeenCalledWith(
      "Test error",
      expect.objectContaining({
        scope: "unit",
        error: expect.objectContaining({
          message: "boom",
          name: "Error",
        }),
      })
    )
  })

  it("installs global handlers that log browser errors and promise rejections", () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined)

    installGlobalErrorLogging()

    window.dispatchEvent(new ErrorEvent("error", { message: "window broke" }))
    const rejectionEvent = new Event("unhandledrejection")
    Object.defineProperty(rejectionEvent, "reason", { value: new Error("promise broke") })
    window.dispatchEvent(rejectionEvent)

    expect(consoleErrorSpy).toHaveBeenCalledTimes(2)
    expect(consoleErrorSpy.mock.calls[0][0]).toBe("Unhandled window error")
    expect(consoleErrorSpy.mock.calls[1][0]).toBe("Unhandled promise rejection")
  })
})
