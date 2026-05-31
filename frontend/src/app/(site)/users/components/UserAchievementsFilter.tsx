"use client";

import React, { useMemo, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import type { UserTournamentSummary } from "@/types/user.types";
import { Filter } from "lucide-react";

const FILTER_QUERY_KEY = "achievementTournamentId";

interface UserAchievementsFilterProps {
  tournaments: UserTournamentSummary[];
  selectedValue: string;
}

const UserAchievementsFilter = ({ tournaments, selectedValue }: UserAchievementsFilterProps) => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  const uniqueTournaments = useMemo(() => {
    const seen = new Set<number>();
    return tournaments.filter((tournament) => {
      if (seen.has(tournament.id)) {
        return false;
      }
      seen.add(tournament.id);
      return true;
    });
  }, [tournaments]);

  const onValueChange = (value: string) => {
    const nextSearchParams = new URLSearchParams(searchParams.toString());

    if (value === "all") {
      nextSearchParams.delete(FILTER_QUERY_KEY);
    } else {
      nextSearchParams.set(FILTER_QUERY_KEY, value);
    }

    startTransition(() => {
      router.push(`${pathname}?${nextSearchParams.toString()}`);
    });
  };

  return (
    <div className="flex items-center gap-2.5">
      <Filter className="h-3.5 w-3.5 text-white/30 shrink-0" />
      <Select value={selectedValue} onValueChange={onValueChange}>
        <SelectTrigger className="h-8 w-full sm:w-64 border-white/[0.07] bg-white/[0.02] text-sm text-white/80 shadow-none hover:border-white/[0.13] hover:bg-white/[0.04] focus:ring-1 focus:ring-white/[0.15] focus:ring-offset-0">
          <SelectValue placeholder="All tournaments" />
        </SelectTrigger>
        <SelectContent className="max-h-[min(var(--radix-select-content-available-height),20rem)]">
          <SelectItem value="all">All tournaments</SelectItem>
          <SelectItem value="none">Without tournament</SelectItem>
          {uniqueTournaments.map((tournament) => (
            <SelectItem key={tournament.id} value={`t-${tournament.id}`}>
              {tournament.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
};

export default UserAchievementsFilter;
