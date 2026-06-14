"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import tournamentService from "@/services/tournament.service";

function getTournamentFromSearch(searchParams: { get(name: string): string | null }): number | null {
  const raw = searchParams.get("tournament");
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

export function BalancerTournamentSelect() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();

  const selectedTournamentId = getTournamentFromSearch(searchParams);

  const tournamentsQuery = useQuery({
    queryKey: ["balancer-public", "tournaments"],
    queryFn: () => tournamentService.getAll(),
    staleTime: Number.POSITIVE_INFINITY,
  });

  const handleTournamentChange = (value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (!value) {
      params.delete("tournament");
    } else {
      params.set("tournament", value);
    }

    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname);
  };

  return (
    <div className="w-full min-w-0 max-w-56">
      <Select value={selectedTournamentId ? String(selectedTournamentId) : undefined} onValueChange={handleTournamentChange}>
        <SelectTrigger className="h-9 w-full bg-background/80">
          <SelectValue placeholder="Select tournament" />
        </SelectTrigger>
        <SelectContent>
          {(tournamentsQuery.data?.results ?? []).map((tournament) => (
            <SelectItem key={tournament.id} value={String(tournament.id)}>
              {tournament.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
