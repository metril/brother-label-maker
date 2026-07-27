import { useQuery } from "@tanstack/react-query";
import { getPrinterStatus } from "../api/client";

const REFETCH_INTERVAL_MS = 10_000;

export function usePrinterStatus() {
  return useQuery({
    queryKey: ["printer-status"],
    queryFn: getPrinterStatus,
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}
