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
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { PlaceBadge } from "@/components/ui/place-badge";
import { RowButton } from "@/components/ui/row-button";
import { SearchField } from "@/components/ui/search-field";
import {
  type TournamentGroup,
  groupAggregate,
  groupBestPlacement,
  groupDisplayName,
  groupEntries,
  groupRepId,
  isLeagueGroup,
  mapsWinratePct
} from "@/app/(site)/users/components/tournaments/tournaments-history.helpers";

type Filter = "all" | "titles" | "podium" | "leagues";

interface Props {
  groups: TournamentGroup[];
  selectedKey: number | null;
  onSelect: (repId: number) => void;
  /** "All games": each row marks its tournament's game. */
  showGames?: boolean;
}

const matchesFilter = (group: TournamentGroup, filter: Filter): boolean => {
  if (filter === "titles") return groupBestPlacement(group) === 1;
  if (filter === "podium") {
    const best = groupBestPlacement(group);
    return best != null && best <= 3;
  }
  if (filter === "leagues") return isLeagueGroup(group);
  return true;
};

const TournamentRow = ({
  group,
  selected,
  onSelect,
  showGames
}: {
  group: TournamentGroup;
  selected: boolean;
  onSelect: () => void;
  showGames: boolean;
}) => {
  const t = useTranslations();
  const league = isLeagueGroup(group);
  const entries = groupEntries(group);
  const best = groupBestPlacement(group);
  const agg = groupAggregate(group);
  const wr = mapsWinratePct(agg.mapsWon, agg.mapsLost);
  const lead: UserTournament = entries[0];
  // Each row draws its role in the event's own game and workspace dictionary.
  const ontology = useDisciplineMetadata(lead.workspace_id, lead.discipline).data ?? null;

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
      <PlaceBadge place={best} size="md" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          {showGames ? <GameIcon slug={lead.discipline} /> : null}
          <span className="truncate text-body font-semibold text-[color:var(--aqt-fg)]">{groupDisplayName(group)}</span>
          {league ? (
            <Badge tone="neutral" voice="label">
              {t("users.tournaments.leagueBadge")}
            </Badge>
          ) : null}
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 text-label text-[color:var(--aqt-fg-dim)]">
          {league ? (
            <span className="truncate">{t("users.tournaments.divisionsCount", { count: String(entries.length) })}</span>
          ) : (
            <>
              <PlayerRoleIcon role={lead.role} ontology={ontology} size={13} />
              <span className="truncate">{t("users.tournaments.teamName", { name: String(lead.team) })}</span>
            </>
          )}
          {wr != null ? (
            <span className="aqt-tnum ml-auto shrink-0 pl-2 text-[color:var(--aqt-fg-faint)]">
              {t("users.tournaments.list.mapsWr", { maps: String(agg.mapsWon + agg.mapsLost), wr: String(Math.round(wr)) })}
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

const TournamentList = ({ groups, selectedKey, onSelect, showGames = false }: Props) => {
  const t = useTranslations();
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");

  const searched = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return groups;
    return groups.filter((group) => groupDisplayName(group).toLowerCase().includes(query));
  }, [groups, search]);

  const counts = useMemo(
    () => ({
      all: searched.length,
      titles: searched.filter((group) => matchesFilter(group, "titles")).length,
      podium: searched.filter((group) => matchesFilter(group, "podium")).length,
      leagues: searched.filter((group) => matchesFilter(group, "leagues")).length
    }),
    [searched]
  );

  const visible = useMemo(() => searched.filter((group) => matchesFilter(group, filter)), [searched, filter]);

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
          {t("users.tournaments.list.eventsCount", { count: String(groups.length) })}
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
          <FilterChip active={filter === "leagues"} count={counts.leagues} onClick={() => setFilter("leagues")}>
            {t("users.tournaments.list.filter.leagues")}
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
          {visible.map((group) => {
            const repId = groupRepId(group);
            return (
              <TournamentRow
                key={repId}
                group={group}
                selected={repId === selectedKey}
                onSelect={() => onSelect(repId)}
                showGames={showGames}
              />
            );
          })}
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
