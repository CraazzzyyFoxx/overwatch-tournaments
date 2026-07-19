"use client";

import React, { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { UserTournament } from "@/types/user.types";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { PlaceBadge, LeagueBadge, WdlText, WdlBar } from "@/app/(site)/users/components/tournaments/tournaments-history.atoms";
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

const ChipButton = ({
  active,
  count,
  onClick,
  children
}: {
  active: boolean;
  count: number;
  onClick: () => void;
  children: React.ReactNode;
}) => (
  <button
    type="button"
    onClick={onClick}
    className={cn(
      "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]",
      active
        ? "border-[color:var(--aqt-teal)] bg-[hsl(172_70%_49%/0.12)] text-[color:var(--aqt-teal)]"
        : "border-[color:var(--aqt-border)] text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]"
    )}
  >
    {children}
    <span className="aqt-mono aqt-tnum text-[10.5px] opacity-80">{count}</span>
  </button>
);

const TournamentRow = ({
  group,
  selected,
  onSelect
}: {
  group: TournamentGroup;
  selected: boolean;
  onSelect: () => void;
}) => {
  const t = useTranslations();
  const league = isLeagueGroup(group);
  const entries = groupEntries(group);
  const best = groupBestPlacement(group);
  const agg = groupAggregate(group);
  const wr = mapsWinratePct(agg.mapsWon, agg.mapsLost);
  const lead: UserTournament = entries[0];

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "flex w-full items-center gap-3 border-b border-[color:var(--aqt-border)] px-3.5 py-3 text-left transition-colors last:border-b-0",
        selected ? "bg-[hsl(172_70%_49%/0.06)]" : "hover:bg-[hsl(0_0%_100%/0.02)]"
      )}
      style={selected ? { boxShadow: "inset 2px 0 0 0 var(--aqt-teal)" } : undefined}
    >
      <PlaceBadge placement={best} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-[14px] font-semibold text-[color:var(--aqt-fg)]">{groupDisplayName(group)}</span>
          {league ? <LeagueBadge>{t("users.tournaments.leagueBadge")}</LeagueBadge> : null}
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 text-[12px] text-[color:var(--aqt-fg-dim)]">
          {league ? (
            <span className="truncate">{t("users.tournaments.divisionsCount", { count: String(entries.length) })}</span>
          ) : (
            <>
              <span className="inline-flex shrink-0" title={lead.role ?? undefined}>
                <PlayerRoleIcon role={lead.role} size={13} />
              </span>
              <span className="truncate">{t("users.tournaments.teamName", { name: String(lead.team) })}</span>
            </>
          )}
          {wr != null ? (
            <span className="aqt-mono ml-auto shrink-0 pl-2 text-[color:var(--aqt-fg-faint)]">
              {t("users.tournaments.list.mapsWr", { maps: String(agg.mapsWon + agg.mapsLost), wr: String(Math.round(wr)) })}
            </span>
          ) : null}
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <WdlText won={agg.won} lost={agg.lost} draw={agg.draw} className="text-[12px]" />
        <WdlBar won={agg.won} lost={agg.lost} draw={agg.draw} />
      </div>
    </button>
  );
};

const TournamentList = ({ groups, selectedKey, onSelect }: Props) => {
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
    <div className="aqt-card-surface flex flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-[color:var(--aqt-border)] px-4 py-3">
        <span className="aqt-card-title">
          <span className="truncate">{t("users.tournaments.list.title")}</span>
        </span>
        <span className="aqt-mono text-[11px] text-[color:var(--aqt-fg-dim)]">
          {t("users.tournaments.list.eventsCount", { count: String(groups.length) })}
        </span>
      </div>

      <div className="flex flex-col gap-2.5 border-b border-[color:var(--aqt-border)] px-4 py-3">
        <div className="flex flex-wrap gap-2">
          <ChipButton active={filter === "all"} count={counts.all} onClick={() => setFilter("all")}>
            {t("users.tournaments.list.filter.all")}
          </ChipButton>
          <ChipButton active={filter === "titles"} count={counts.titles} onClick={() => setFilter("titles")}>
            {t("users.tournaments.list.filter.titles")}
          </ChipButton>
          <ChipButton active={filter === "podium"} count={counts.podium} onClick={() => setFilter("podium")}>
            {t("users.tournaments.list.filter.podium")}
          </ChipButton>
          <ChipButton active={filter === "leagues"} count={counts.leagues} onClick={() => setFilter("leagues")}>
            {t("users.tournaments.list.filter.leagues")}
          </ChipButton>
        </div>
        <div className="relative">
          <Search
            size={14}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]"
          />
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("users.tournaments.list.searchPlaceholder")}
            aria-label={t("users.tournaments.list.searchPlaceholder")}
            className="w-full rounded-[8px] border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] py-1.5 pl-8 pr-2.5 text-[13px] text-[color:var(--aqt-fg)] placeholder:text-[color:var(--aqt-fg-faint)] focus-visible:border-[color:var(--aqt-teal)] focus-visible:outline-none"
          />
        </div>
      </div>

      {visible.length > 0 ? (
        <div className="max-h-[720px] overflow-y-auto">
          {visible.map((group) => {
            const repId = groupRepId(group);
            return (
              <TournamentRow
                key={repId}
                group={group}
                selected={repId === selectedKey}
                onSelect={() => onSelect(repId)}
              />
            );
          })}
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
          <span className="text-[13px] text-[color:var(--aqt-fg-muted)]">{t("users.tournaments.list.empty")}</span>
          <button
            type="button"
            onClick={resetFilters}
            className="aqt-mono text-[11px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-teal)] hover:underline"
          >
            {t("users.tournaments.list.resetFilters")}
          </button>
        </div>
      )}
    </div>
  );
};

export default TournamentList;
