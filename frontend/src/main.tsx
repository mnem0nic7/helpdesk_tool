import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import App from "./App";
import AppErrorBoundary from "./components/AppErrorBoundary";
import { installGlobalErrorLogging, logClientError } from "./lib/errorLogging";

installGlobalErrorLogging()

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      logClientError("React Query error", error, {
        queryKey: query.queryKey,
      })
    },
  }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      logClientError("React Query mutation error", error, {
        mutationKey: mutation.options.mutationKey ?? null,
      })
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </AppErrorBoundary>
  </StrictMode>
);
