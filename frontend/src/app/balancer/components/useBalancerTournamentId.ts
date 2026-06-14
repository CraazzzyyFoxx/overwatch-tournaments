"use client";

import { useSearchParams } from "next/navigation";

export function useBalancerTournamentId(): number | null {
  const searchParams = useSearchParams();
  const raw = searchParams.get("tournament");
  if (!raw) {
    return null;
  }

  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}
