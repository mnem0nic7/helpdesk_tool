type ErrorContext = Record<string, unknown>

let globalLoggingInstalled = false

function normalizeError(error: unknown): unknown {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack,
    }
  }
  return error
}

export function logClientError(message: string, error: unknown, context: ErrorContext = {}) {
  console.error(message, {
    ...context,
    error: normalizeError(error),
  })
}

export function installGlobalErrorLogging() {
  if (globalLoggingInstalled || typeof window === "undefined") {
    return
  }

  window.addEventListener("error", (event) => {
    logClientError("Unhandled window error", event.error ?? event.message, {
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
    })
  })

  window.addEventListener("unhandledrejection", (event) => {
    logClientError("Unhandled promise rejection", event.reason)
  })

  globalLoggingInstalled = true
}

