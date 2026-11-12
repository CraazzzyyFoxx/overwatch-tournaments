"use client";

import { useMemo, useState } from "react";
import { SearchX } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { UserTournament } from "@/types/user.types";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { GameIcon } from "@/components/workspace/GameIcon";
import { WdlText, WdlBar } from "@/app/(site)/users/components/tournaments/tournaments-history.atoms";
import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { FilterChip, FilterChipGroup } from "@craazzzyyfoxx/admin-kit/ui/filter-chip";
import { PlaceBadge } from "@/components/ui/place-badge";
import { RowButton } from "@craazzzyyfoxx/admin-kit/ui/row-button";
import { SearchField } from "@craazzzyyfoxx/admin-kit/ui/search-field";
import {
  mapsWinratePct,
  tournamentAggregate
} from "@/app/(site)/users/components/tournaments/tournaments-history.helpers";

type Filter = "all" | "titles" | "podium";

interface Props {
  tournaments: UserTournament[];
  selectedId: number | null;
  onSelect: (tournamentId: number) => void;
  /** "All games": each row marks its tournament's game. */
  showGames?: boolean;
}

const matchesFilter = (t: UserTournament, filter: Filter): boolean => {
  if (filter === "titles") return t.placement === 1;
  if (filter === "podium") return t.placement != null && t.placement >= 1 && t.placement <= 3;
  return true;
};

const TournamentRow = ({
  tournament: t,
  selected,
  onSelect,
  showGames
}: {
  tournament: UserTournament;
  selected: boolean;
  onSelect: () => void;
  showGames: boolean;
}) => {
  const tr = useTranslations();
  const agg = tournamentAggregate(t);
  const wr = mapsWinratePct(agg.mapsWon, agg.mapsLost);
  // Each row draws its role in the event's own game and workspace dictionary.
  const ontology = useDisciplineMetadata(t.workspace_id, t.discipline).data ?? null;

  return (
    <RowButton
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "flex items-center gap-3 border-b border-[color:var(--aqt-border)] px-3.5 py-3 last:border-b-0",
        selected && "bg-[color:color-mix(in_srgb,var(--aqt-teal)_6%,transparent)]"
      )}
      style={selected ? { boxShadow: "inset 2px 0 0 0 var(--aqt-teal)" } : undefined}
    >
      <PlaceBadge place={t.placement ?? null} size="md" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          {showGames ? <GameIcon slug={t.discipline} /> : null}
          <span className="truncate text-body font-semibold text-[color:var(--aqt-fg)]">{t.name}</span>
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 text-label text-[color:var(--aqt-fg-dim)]">
          <PlayerRoleIcon role={t.role} ontology={ontology} size={13} />
          <span className="truncate">{tr("users.tournaments.teamName", { name: String(t.team) })}</span>
          {wr != null ? (
            <span className="aqt-tnum ml-auto shrink-0 pl-2 text-[color:var(--aqt-fg-faint)]">
              {tr("users.tournaments.list.mapsWr", { maps: String(agg.mapsWon + agg.mapsLost), wr: String(Math.round(wr)) })}
            </span>
          ) : null}
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <WdlText won={agg.won} lost={agg.lost} draw={agg.draw} className="text-label" />
        <WdlBar won={agg.won} lost={agg.lost} draw={agg.draw} />
      </div>
    </RowButton>
  );
};

const TournamentList = ({ tournaments, selectedId, onSelect, showGames = false }: Props) => {
  const t = useTranslations();
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");

  const searched = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return tournaments;
    return tournaments.filter((tournament) => tournament.name.toLowerCase().includes(query));
  }, [tournaments, search]);

  const counts = useMemo(
    () => ({
      all: searched.length,
      titles: searched.filter((tournament) => matchesFilter(tournament, "titles")).length,
      podium: searched.filter((tournament) => matchesFilter(tournament, "podium")).length
    }),
    [searched]
  );

  const visible = useMemo(() => searched.filter((tournament) => matchesFilter(tournament, filter)), [searched, filter]);

  const resetFilters = () => {
    setFilter("all");
    setSearch("");
  };

  return (
    <Card className="flex flex-col overflow-hidden min-[1081px]:absolute min-[1081px]:inset-0">
      <div className="flex items-center justify-between gap-2 border-b border-[color:var(--aqt-border)] px-4 py-3">
        <CardTitle asChild className="truncate font-display text-[color:var(--aqt-fg)]">
          <h2>{t("users.tournaments.list.title")}</h2>
        </CardTitle>
        <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
          {t("users.tournaments.list.eventsCount", { count: String(tournaments.length) })}
        </span>
      </div>

      <div className="flex flex-col gap-2.5 border-b border-[color:var(--aqt-border)] px-4 py-3">
        <FilterChipGroup label={t("common.filters")}>
          <FilterChip active={filter === "all"} count={counts.all} onClick={() => setFilter("all")}>
            {t("users.tournaments.list.filter.all")}
          </FilterChip>
          <FilterChip active={filter === "titles"} count={counts.titles} onClick={() => setFilter("titles")}>
            {t("users.tournaments.list.filter.titles")}
          </FilterChip>
          <FilterChip active={filter === "podium"} count={counts.podium} onClick={() => setFilter("podium")}>
            {t("users.tournaments.list.filter.podium")}
          </FilterChip>
        </FilterChipGroup>
        <SearchField
          value={search}
          onValueChange={setSearch}
          label={t("users.tournaments.list.searchPlaceholder")}
          placeholder={t("users.tournaments.list.searchPlaceholder")}
        />
      </div>

      {visible.length > 0 ? (
        <div className="max-h-[720px] overflow-y-auto min-[1081px]:max-h-none min-[1081px]:min-h-0 min-[1081px]:flex-1">
          {visible.map((tournament) => (
            <TournamentRow
              key={tournament.id}
              tournament={tournament}
              selected={tournament.id === selectedId}
              onSelect={() => onSelect(tournament.id)}
              showGames={showGames}
            />
          ))}
        </div>
      ) : (
        <EmptyNote
          icon={SearchX}
          className="m-4"
          action={
            <Button variant="outline" size="sm" onClick={resetFilters}>
              {t("users.tournaments.list.resetFilters")}
            </Button>
          }
        >
          {t("users.tournaments.list.empty")}
        </EmptyNote>
      )}
    </Card>
  );
};

export default TournamentList;
