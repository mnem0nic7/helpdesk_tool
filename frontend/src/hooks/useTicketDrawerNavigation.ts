import { useCallback } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

export default function useTicketDrawerNavigation() {
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();

  const ticketKey = searchParams.get("ticket");

  const buildTicketHref = useCallback(
    (key: string) => {
      const next = new URLSearchParams(searchParams);
      next.set("ticket", key);
      const query = next.toString();
      return query ? `${location.pathname}?${query}` : location.pathname;
    },
    [location.pathname, searchParams],
  );

  const openTicketByKey = useCallback(
    (key: string, replace = false) => {
      const next = new URLSearchParams(searchParams);
      next.set("ticket", key);
      setSearchParams(next, replace ? { replace: true } : undefined);
    },
    [searchParams, setSearchParams],
  );

  const closeTicket = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    next.delete("ticket");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  return {
    ticketKey,
    buildTicketHref,
    openTicketByKey,
    closeTicket,
  };
}
