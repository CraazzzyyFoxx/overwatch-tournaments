"use client";

import { useMemo, useState } from "react";
import { History } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { UserTournament } from "@/types/user.types";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import {
  groupTournamentsByLeague,
  leagueKey
} from "@/app/(site)/users/components/tournaments/tournaments-history.helpers";
import TournamentItem from "@/app/(site)/users/components/tournaments/TournamentItem";
import LeagueGroup from "@/app/(site)/users/components/tournaments/LeagueGroup";

interface Props {
  tournaments: UserTournament[];
  selfUserId: number;
}

// ─── Main component ─────────────────────────────────────────────────────────────

const TournamentsHistory = ({ tournaments, selfUserId }: Props) => {
  const searchParams = useSearchParams();
  const selectedId = useMemo(() => {
    const raw = searchParams?.get("selectedTournamentId");
    const parsed = raw ? Number(raw) : NaN;
    return Number.isFinite(parsed) ? parsed : null;
  }, [searchParams]);

  // Group consecutive league entries (sharing the league-name prefix) under one parent.
  const grouped = useMemo(() => groupTournamentsByLeague(tournaments), [tournaments]);

  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [expandedLeagues, setExpandedLeagues] = useState<Record<string, boolean>>({});

  const syncUrl = (id: number, open: boolean) => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (open) url.searchParams.set("selectedTournamentId", String(id));
    else url.searchParams.delete("selectedTournamentId");
    window.history.replaceState(null, "", url.toString());
  };

  const isTournamentOpen = (t: UserTournament) => expanded[t.id] ?? t.id === selectedId;

  const toggleTournament = (t: UserTournament) => {
    const next = !isTournamentOpen(t);
    setExpanded((s) => ({ ...s, [t.id]: next }));
    syncUrl(t.id, next);
  };

  const isLeagueOpen = (name: string, entries: UserTournament[]) =>
    expandedLeagues[name] ?? entries.some((t) => t.id === selectedId);

  return (
    <CardSurface flush title="Tournament history" icon={<History size={15} />} subtitle="click to expand">
      {grouped.map((entry) => {
        if (!Array.isArray(entry)) {
          return (
            <TournamentItem
              key={entry.id}
              t={entry}
              selfUserId={selfUserId}
              isOpen={isTournamentOpen(entry)}
              onToggle={() => toggleTournament(entry)}
            />
          );
        }
        const name = leagueKey(entry[0]);
        return (
          <LeagueGroup
            key={name}
            name={name}
            entries={entry}
            selfUserId={selfUserId}
            isOpen={isLeagueOpen(name, entry)}
            onToggle={() => setExpandedLeagues((s) => ({ ...s, [name]: !isLeagueOpen(name, entry) }))}
            isTournamentOpen={isTournamentOpen}
            onToggleTournament={toggleTournament}
          />
        );
      })}
    </CardSurface>
  );
};

export default TournamentsHistory;
