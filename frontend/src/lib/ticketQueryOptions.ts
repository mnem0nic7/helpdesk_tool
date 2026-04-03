import { getPollingQueryOptions } from "./queryPolling.ts";

export const ACTIVE_TICKET_LIST_REFETCH_MS = 60_000;

export const activeTicketListQueryOptions = getPollingQueryOptions("live_60s", {
  staleTime: ACTIVE_TICKET_LIST_REFETCH_MS,
});
