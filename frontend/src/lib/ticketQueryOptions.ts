export const ACTIVE_TICKET_LIST_REFETCH_MS = 15_000;

export const activeTicketListQueryOptions = {
  staleTime: 5_000,
  refetchInterval: ACTIVE_TICKET_LIST_REFETCH_MS,
  refetchIntervalInBackground: false,
  refetchOnWindowFocus: true,
} as const;
