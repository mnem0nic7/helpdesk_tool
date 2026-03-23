export const ACTIVE_TICKET_LIST_REFETCH_MS = 60_000;

export const activeTicketListQueryOptions = {
  staleTime: ACTIVE_TICKET_LIST_REFETCH_MS,
  refetchInterval: ACTIVE_TICKET_LIST_REFETCH_MS,
  refetchIntervalInBackground: false,
  refetchOnWindowFocus: true,
} as const;
