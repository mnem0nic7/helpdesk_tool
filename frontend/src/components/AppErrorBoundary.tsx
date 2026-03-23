import { Component, type ErrorInfo, type ReactNode } from "react"
import { logClientError } from "../lib/errorLogging"

type AppErrorBoundaryProps = {
  children: ReactNode
}

type AppErrorBoundaryState = {
  hasError: boolean
}

export default class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = {
    hasError: false,
  }

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    logClientError("React render error", error, {
      componentStack: errorInfo.componentStack,
    })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-slate-100 px-6">
          <div className="max-w-md rounded-3xl border border-rose-200 bg-white p-8 text-center shadow-sm">
            <h1 className="text-lg font-semibold text-slate-900">Something went wrong</h1>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              The error has been logged. Refresh the page to try again, and let the team know if it keeps happening.
            </p>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}

