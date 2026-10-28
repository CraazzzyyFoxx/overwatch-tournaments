"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronUp, ImageOff } from "lucide-react";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { characterClassOf } from "@/components/pick-ban/pick-ban-model";
import PlayerName from "@/components/PlayerName";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { CardSurface, ProfileStat } from "@/components/profile/atoms";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import Image from "@/components/ui/image";
import { SearchField } from "@/components/ui/search-field";
import { useCatalogEntities } from "@/hooks/useCatalogEntities";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { useFormatter } from "@/lib/datetime/client";
import { isEncounterCompleted } from "@/lib/encounter/status";
import { roleColor, type RoleOntology } from "@/lib/roster/ontology";
import { tournamentCharacterPlaytimeQueryOptions } from "@/lib/tournament/character-playtime-query";
import { tournamentEncountersQueryOptions } from "@/lib/tournament/encounters-query";
import type { PlayerStat } from "@/lib/tournament/insights-query";
import { isTournamentStatusEnded } from "@/lib/tournament/status";
import { tournamentHref } from "@/lib/tournament/url";
import { cn } from "@/lib/utils";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { Encounter } from "@/types/encounter.types";
import type { Tournament, TournamentPlayerStatKey } from "@/types/tournament.types";
import type { CharacterPlaytime } from "@/types/user.types";

import { TournamentPageState } from "../_components/TournamentPageState";
import {
  TournamentHeroesSkeleton,
  TournamentMapsSkeleton
} from "../_components/TournamentSkeletons";
import { readViewParam, ViewSegment } from "../_components/ViewSegment";
import { useTournamentInsights } from "../_hooks/useTournamentInsights";
import { useTournamentMapPool } from "../_hooks/useTournamentMapPool";
import { CardColumns, wideOnly } from "./_components/OverviewCards";
import { SortableTable, type SortableColumn } from "./_components/SortableTable";
import {
  aggregateBans,
  baseRole,
  isTournamentRole,
  oneTricks,
  rankLabel,
  ROLE_ORDER,
  STAT_META
} from "./tournamentInsights.model";
import { useTournamentRoster, type RosterEntry } from "./useTournamentRoster";

const TABS = ["players", "bans", "heroes", "maps"] as const;

export type MapPlayedCount = {
  played: number;
  /** Mean map duration in seconds, or null when no map has a recorded length. */
  avgDurationSec: number | null;
};

/**
 * How often each map was played, and how long it took, from the tournament's
 * own series. No attack/defense split: a `Match` carries a score, a duration
 * and a map, and nothing in the read model says which team attacked.
 */
export function buildMapPlayedCounts(
  encounters: readonly Encounter[]
): Record<number, MapPlayedCount> {
  const totals = new Map<number, { played: number; durationSec: number; timed: number }>();

  for (const encounter of encounters) {
    for (const match of encounter.matches ?? []) {
      const entry = totals.get(match.map_id) ?? { played: 0, durationSec: 0, timed: 0 };
      entry.played += 1;
      if (match.duration_s != null) {
        entry.durationSec += match.duration_s;
        entry.timed += 1;
      }
      totals.set(match.map_id, entry);
    }
  }

  const counts: Record<number, MapPlayedCount> = {};
  for (const [mapId, entry] of totals) {
    counts[mapId] = {
      played: entry.played,
      avgDurationSec: entry.timed > 0 ? entry.durationSec / entry.timed : null
    };
  }
  return counts;
}

/** The tournament's statistics: players and bans, then the characters and the maps played. */
export default function TournamentStatsPage({ slug }: Readonly<{ slug: string }>) {
  const t = useTranslations("tournamentDetail");
  const searchParams = useSearchParams();
  const tab = readViewParam(searchParams, "tab", TABS, "players");
  const tournamentQuery = useTournamentQuery(slug);
  const tournament = tournamentQuery.data;
  if (!tournament) {
    return tournamentQuery.isError ? (
      <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
    ) : (
      <TournamentHeroesSkeleton />
    );
  }

  return (
    <section
      className="grid w-full min-w-0 max-w-full gap-4 *:min-w-0"
      aria-label={t("stats.title")}
    >
      <div className="flex min-w-0 max-w-full overflow-x-auto py-0.5 [scrollbar-width:thin] *:flex-none">
        <ViewSegment
          param="tab"
          options={TABS.map((value) => ({ value, label: t(`stats.tabs.${value}`) }))}
          defaultValue="players"
          label={t("stats.tabsLabel")}
          hideOnMobile={false}
        />
      </div>
      {tab === "players" ? (
        <PlayersTab tournament={tournament} />
      ) : tab === "bans" ? (
        <BansTab tournament={tournament} />
      ) : tab === "maps" ? (
        <MapsTab tournament={tournament} slug={slug} />
      ) : (
        <HeroesTab tournament={tournament} />
      )}
    </section>
  );
}

type PlayerRow = {
  entry: RosterEntry;
  role: string | null;
  stats: Partial<Record<TournamentPlayerStatKey, PlayerStat>>;
};

const LEADER_STATS: TournamentPlayerStatKey[] = [
  "performance",
  "kda",
  "eliminations",
  "hero_damage_dealt",
  "assists",
  "deaths"
];

function useStatFormat() {
  const format = useFormatter();
  return (stat: TournamentPlayerStatKey, value: number) =>
    format.number(value, {
      minimumFractionDigits: STAT_META[stat].digits,
      maximumFractionDigits: STAT_META[stat].digits
    });
}

function PlayerCell({
  row,
  ontology
}: Readonly<{ row: PlayerRow; ontology: RoleOntology | null }>) {
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <PlayerRoleIcon role={row.entry.player.role} ontology={ontology} size={16} decorative />
      <span className="min-w-0">
        <PlayerName player={row.entry.player} className="max-w-[14rem] text-caption" />
        <span className="block truncate text-label text-[color:var(--aqt-fg-dim)]">
          {row.entry.team.name}
        </span>
      </span>
    </span>
  );
}

function PlayersTab({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations("tournamentDetail");
  const insights = useTournamentInsights(tournament);
  const roster = useTournamentRoster(tournament);
  const ontology =
    useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;
  const show = useStatFormat();
  const [role, setRole] = useState<string>("all");
  const [query, setQuery] = useState("");

  const rows = useMemo<PlayerRow[]>(
    () =>
      [...roster.byUser.values()].map((entry) => ({
        entry,
        role: baseRole(entry.player.role?.role),
        stats: insights.players[entry.player.user_id] ?? {}
      })),
    [roster.byUser, insights.players]
  );
  const needle = query.trim().toLowerCase();
  const visible = rows.filter(
    (row) =>
      (role === "all" || row.role === role) &&
      (needle === "" ||
        row.entry.player.name.toLowerCase().includes(needle) ||
        row.entry.team.name.toLowerCase().includes(needle))
  );

  const statColumn = (stat: TournamentPlayerStatKey): SortableColumn<PlayerRow> => ({
    key: stat,
    label: t(`stats.metrics.${stat}.short`),
    title: stat === "performance" ? t("stats.performanceHint") : t(`stats.metrics.${stat}.label`),
    numeric: true,
    ascendingFirst: STAT_META[stat].lowerIsBetter,
    sortValue: (row) => row.stats[stat]?.value ?? null,
    cell: (row) => {
      const value = row.stats[stat];
      if (!value) return <span className="text-[color:var(--aqt-fg-faint)]">—</span>;
      return (
        <span
          className={cn(
            value.rank <= 3 && "font-semibold text-[color:var(--aqt-fg)]",
            value.rank === 1 && "text-[color:var(--aqt-teal)]"
          )}
          title={t("common.rankOf", { rank: value.rank, total: insights.playersTotal })}
        >
          {show(stat, value.value)}
        </span>
      );
    }
  });
  const columns: SortableColumn<PlayerRow>[] = [
    {
      key: "name",
      label: t("stats.players.player"),
      sortValue: (row) => row.entry.player.name.toLowerCase(),
      ascendingFirst: true,
      cell: (row) => <PlayerCell row={row} ontology={ontology} />
    },
    statColumn("performance"),
    statColumn("kda"),
    statColumn("eliminations"),
    statColumn("deaths"),
    statColumn("assists"),
    statColumn("hero_damage_dealt"),
    statColumn("damage_delta")
  ];

  return (
    <div className="grid gap-4">
      <CardSurface title={t("stats.players.leaders")}>
        <div className="grid gap-x-10 gap-y-8 sm:grid-cols-2 xl:grid-cols-3">
          {LEADER_STATS.map((stat) => {
            const [first, ...rest] = rows
              .filter((row) => row.stats[stat])
              .sort((a, b) => (a.stats[stat]?.rank ?? 0) - (b.stats[stat]?.rank ?? 0))
              .slice(0, 3);
            if (!first) return null;
            return (
              <section key={stat} className="grid min-w-0 content-start gap-3">
                <Eyebrow as="h3" className="truncate" title={t(`stats.metrics.${stat}.label`)}>
                  {t(`stats.metrics.${stat}.label`)}
                </Eyebrow>
                {/* The leader reads as the headline; second and third are the context under it. */}
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-3">
                  <PlayerCell row={first} ontology={ontology} />
                  <span className="aqt-tnum font-onest text-title leading-none font-bold">
                    {show(stat, first.stats[stat]?.value ?? 0)}
                  </span>
                </div>
                <ol className="grid gap-1.5 border-t border-[color:var(--aqt-border)] pt-2.5">
                  {rest.map((row, index) => (
                    <li
                      key={row.entry.player.id}
                      className="grid grid-cols-[16px_minmax(0,1fr)_auto] items-center gap-x-2.5"
                    >
                      {/* The place sits in the leader's role-icon column, so all three names start on one line. */}
                      <span
                        aria-hidden
                        className="aqt-tnum text-center text-label text-[color:var(--aqt-fg-faint)]"
                      >
                        {index + 2}
                      </span>
                      <PlayerName player={row.entry.player} className="text-caption" />
                      <span className="aqt-tnum text-caption text-[color:var(--aqt-fg-muted)]">
                        {show(stat, row.stats[stat]?.value ?? 0)}
                      </span>
                    </li>
                  ))}
                </ol>
              </section>
            );
          })}
        </div>
      </CardSurface>
      <CardSurface
        title={t("stats.players.all")}
        subtitle={t("common.shownOf", { shown: visible.length, total: rows.length })}
        flush
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-[color:var(--aqt-border)] px-4.5 py-3">
          <FilterChipGroup label={t("stats.players.roleFilter")}>
            <FilterChip active={role === "all"} onClick={() => setRole("all")}>
              {t("stats.players.allRoles")}
            </FilterChip>
            {ROLE_ORDER.map((item) => (
              <FilterChip key={item} active={role === item} onClick={() => setRole(item)}>
                {t(`roles.${item}`)}
              </FilterChip>
            ))}
          </FilterChipGroup>
          <SearchField
            label={t("stats.players.search")}
            placeholder={t("stats.players.searchPlaceholder")}
            value={query}
            onValueChange={setQuery}
            containerClassName="w-full sm:ms-auto sm:w-64"
          />
        </div>
        <SortableTable
          rows={visible}
          columns={columns}
          rowKey={(row) => row.entry.player.id}
          defaultSort={{ key: "performance", ascending: true }}
          label={t("stats.players.table")}
          empty={t("stats.players.empty")}
          pageSize={25}
          stickyFirst
        />
        <p className="border-t border-[color:var(--aqt-border)] px-4.5 py-3 text-label text-[color:var(--aqt-fg-dim)]">
          {t("stats.players.footnote", { hint: t("stats.performanceHint") })}
        </p>
      </CardSurface>
    </div>
  );
}

function useCatalogById(discipline: string, kind: "character" | "map") {
  const query = useCatalogEntities(discipline, kind);
  return useMemo(
    () => new Map((query.data ?? []).map((entity) => [entity.id, entity])),
    [query.data]
  );
}

function BansTab({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations("tournamentDetail");
  const heroes = useCatalogById(tournament.discipline, "character");
  const roster = useTournamentRoster(tournament);
  const ontology =
    useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;
  const format = useFormatter();
  const insights = useTournamentInsights(tournament);
  const bans = useMemo(
    () => aggregateBans(insights.heroBans, insights.mapBans),
    [insights.heroBans, insights.mapBans]
  );

  if (insights.isPending) return <TournamentHeroesSkeleton />;

  if (!bans || bans.totalHeroBans === 0) {
    return (
      <TournamentPageState
        state="empty"
        title={t("stats.bans.emptyTitle")}
        description={t("stats.bans.emptyDescription")}
      />
    );
  }

  const leader = bans.heroes[0]?.bans ?? 1;
  const byRole = ROLE_ORDER.map((role) => ({
    role,
    bans: bans.heroes
      .filter((row) => characterClassOf(heroes.get(row.id)) === role)
      .reduce((sum, row) => sum + row.bans, 0)
  }));
  const roleTotal = byRole.reduce((sum, row) => sum + row.bans, 0) || 1;
  const banSwatch = "size-2 shrink-0 rounded-full bg-[color:var(--aqt-rose)]";

  return (
    <div className="grid gap-4">
      <CardSurface
        title={t(
          isTournamentStatusEnded(tournament.status)
            ? "stats.bans.summary"
            : "stats.bans.summarySoFar"
        )}
      >
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
          <ProfileStat
            label={t("overview.numbers.heroBans")}
            value={format.number(bans.totalHeroBans)}
          />
          <ProfileStat label={t("stats.bans.seriesWithBans")} value={bans.series} />
          <ProfileStat
            label={t("stats.bans.distinctHeroes")}
            value={bans.heroes.length}
            sub={heroes.size ? t("common.ofTotal", { total: heroes.size }) : undefined}
          />
          <ProfileStat
            label={t("stats.bans.perSeries")}
            value={format.number(bans.totalHeroBans / Math.max(1, bans.series), {
              maximumFractionDigits: 1
            })}
          />
        </div>
      </CardSurface>

      <CardColumns
        even
        main={
          <CardSurface
            title={t("stats.bans.mostBanned")}
            subtitle={wideOnly(t("stats.bans.mostBannedSub"))}
          >
            <ol className="grid gap-2.5">
              {bans.heroes.slice(0, 15).map((row, index) => {
                const hero = heroes.get(row.id) ?? null;
                return (
                  <li
                    key={row.id}
                    className="grid grid-cols-[1.25rem_28px_minmax(0,1fr)_auto] items-center gap-x-2.5"
                  >
                    <span
                      aria-hidden
                      className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]"
                    >
                      {rankLabel(index)}
                    </span>
                    <CatalogEntityImage entity={hero} size={28} decorative />
                    <span className="flex min-w-0 flex-col gap-1.5">
                      <span className="truncate text-caption font-semibold">
                        {hero?.name ?? `#${row.id}`}
                      </span>
                      {/* One hue, two parts: per player solid, blind faint; the split is in the title and for readers. */}
                      <span
                        className="block h-1.5 rounded-full bg-[color:var(--aqt-overlay-2)]"
                        title={t("stats.bans.split", { blind: row.blind, targeted: row.targeted })}
                      >
                        <span
                          aria-hidden
                          className="flex h-full overflow-hidden rounded-full"
                          style={{ width: `${(row.bans / leader) * 100}%` }}
                        >
                          <span
                            className="h-full bg-[color:var(--aqt-rose)]"
                            style={{ flexGrow: row.targeted }}
                          />
                          <span
                            className="h-full bg-[color:var(--aqt-rose)]/40"
                            style={{ flexGrow: row.blind }}
                          />
                        </span>
                        <span className="sr-only">
                          {t("stats.bans.split", { blind: row.blind, targeted: row.targeted })}
                        </span>
                      </span>
                    </span>
                    <span className="text-right">
                      <span className="aqt-tnum block text-caption font-semibold">{row.bans}</span>
                      <span className="aqt-tnum block text-label text-[color:var(--aqt-fg-dim)]">
                        {t("stats.bans.seriesShare", {
                          share: format.number(row.series / bans.series, {
                            style: "percent",
                            maximumFractionDigits: 0
                          })
                        })}
                      </span>
                    </span>
                  </li>
                );
              })}
            </ol>
            <p className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-label text-[color:var(--aqt-fg-dim)]">
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden className={banSwatch} />
                {t("stats.bans.targeted")}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden className={cn(banSwatch, "opacity-40")} />
                {t("stats.bans.blind")}
              </span>
            </p>
          </CardSurface>
        }
        side={
          <>
            <CardSurface
              title={t("stats.bans.oneTricks")}
              subtitle={wideOnly(t("stats.bans.oneTricksSub"))}
            >
              <ol className="grid gap-3">
                {oneTricks(bans)
                  .slice(0, 9)
                  .map((row, index) => {
                    const entry = roster.byPlayer.get(row.playerId);
                    const hero = heroes.get(row.heroId) ?? null;
                    if (!entry) return null;
                    return (
                      <li
                        key={row.playerId}
                        className="grid grid-cols-[1.25rem_minmax(0,1fr)_28px_auto] items-center gap-x-2.5"
                      >
                        <span
                          aria-hidden
                          className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]"
                        >
                          {rankLabel(index)}
                        </span>
                        <span className="min-w-0">
                          <PlayerName player={entry.player} className="text-caption" />
                          <span className="block truncate text-label text-[color:var(--aqt-fg-dim)]">
                            {entry.team.name}
                          </span>
                        </span>
                        <CatalogEntityImage entity={hero} size={28} title={hero?.name} />
                        <span className="text-right">
                          <span className="aqt-tnum block text-caption font-semibold">
                            {format.number(row.share, {
                              style: "percent",
                              maximumFractionDigits: 0
                            })}
                          </span>
                          <span className="aqt-tnum block text-label text-[color:var(--aqt-fg-dim)]">
                            {t("stats.bans.heroOfTotal", { count: row.heroBans, total: row.bans })}
                          </span>
                        </span>
                      </li>
                    );
                  })}
              </ol>
              <p className="mt-4 text-label text-[color:var(--aqt-fg-dim)]">
                {t("stats.bans.oneTricksNote")}
              </p>
            </CardSurface>

            <CardSurface title={t("stats.bans.byRole")}>
              <ul className="grid gap-3">
                {byRole.map((row) => (
                  <li
                    key={row.role}
                    className="grid grid-cols-[20px_minmax(0,1fr)_auto] items-center gap-x-2.5"
                  >
                    <PlayerRoleIcon role={row.role} ontology={ontology} size={18} decorative />
                    <span className="flex min-w-0 flex-col gap-1">
                      <span className="text-caption font-semibold">{t(`roles.${row.role}`)}</span>
                      <span
                        aria-hidden
                        className="block h-1.5 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]"
                      >
                        <span
                          className="block h-full rounded-full"
                          style={{
                            width: `${(row.bans / roleTotal) * 100}%`,
                            backgroundColor: roleColor(ontology, row.role) ?? "var(--aqt-fg-muted)"
                          }}
                        />
                      </span>
                    </span>
                    <span className="text-right">
                      <span className="aqt-tnum block text-caption font-semibold">
                        {format.number(row.bans / roleTotal, {
                          style: "percent",
                          maximumFractionDigits: 0
                        })}
                      </span>
                      <span className="aqt-tnum block text-label text-[color:var(--aqt-fg-dim)]">
                        {t("stats.bans.roleBans", { count: row.bans })}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </CardSurface>
          </>
        }
      />
    </div>
  );
}

/** A role's column shows its first ten heroes; the rest open on demand, so the three columns start out even. */
const HERO_ROWS = 10;

/** Play time by hero, one column per role: the role's share in the head, each hero's against the role's leader. */
function HeroesTab({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations("tournamentDetail");
  const tRoot = useTranslations();
  const format = useFormatter();
  const ontology =
    useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;
  const query = useQuery(tournamentCharacterPlaytimeQueryOptions(tournament));
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());

  if (!query.data) {
    return query.isError ? (
      <TournamentPageState state="initial-error" onRetry={() => void query.refetch()} />
    ) : (
      <TournamentHeroesSkeleton />
    );
  }
  const byRole = new Map<string, CharacterPlaytime[]>();
  for (const row of [...query.data.results].sort((a, b) => b.playtime - a.playtime)) {
    const role = characterClassOf(row.entity) ?? "—";
    byRole.set(role, [...(byRole.get(role) ?? []), row]);
  }
  if (byRole.size === 0) {
    return (
      <TournamentPageState
        state="empty"
        title={tRoot("tournamentDetail.stats.heroes.emptyTitle")}
        description={tRoot("tournamentDetail.stats.heroes.emptyDescription")}
      />
    );
  }
  const order = (role: string) => {
    const index = (ROLE_ORDER as readonly string[]).indexOf(role);
    return index < 0 ? ROLE_ORDER.length : index;
  };
  const percent = (share: number) =>
    format.number(share, { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 });

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {[...byRole]
        .sort(([a], [b]) => order(a) - order(b))
        .map(([role, rows]) => {
          const expanded = open.has(role);
          const color = roleColor(ontology, role) ?? "var(--aqt-fg-muted)";
          const leader = rows[0]?.playtime || 1;
          return (
            <CardSurface
              key={role}
              title={
                <span className="inline-flex items-center gap-2">
                  {isTournamentRole(role) ? (
                    <PlayerRoleIcon role={role} ontology={ontology} size={16} decorative />
                  ) : null}
                  {isTournamentRole(role) ? t(`roles.${role}`) : role}
                </span>
              }
              subtitle={t("stats.heroes.share", {
                share: percent(rows.reduce((sum, row) => sum + row.playtime, 0))
              })}
            >
              <ol className="grid gap-2.5">
                {(expanded ? rows : rows.slice(0, HERO_ROWS)).map((row, index) => (
                  <li
                    key={row.entity.id}
                    className="grid grid-cols-[1.25rem_28px_minmax(0,1fr)_3.25rem] items-center gap-x-2.5"
                  >
                    <span
                      aria-hidden
                      className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]"
                    >
                      {rankLabel(index)}
                    </span>
                    <CatalogEntityImage entity={row.entity} size={28} decorative />
                    <span className="flex min-w-0 flex-col gap-1.5">
                      <span className="truncate text-caption font-semibold">{row.entity.name}</span>
                      <span
                        aria-hidden
                        className="block h-1.5 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]"
                      >
                        <span
                          className="block h-full rounded-full"
                          style={{
                            width: `${(row.playtime / leader) * 100}%`,
                            backgroundColor: color
                          }}
                        />
                      </span>
                    </span>
                    <span className="aqt-tnum text-right text-caption font-semibold">
                      {percent(row.playtime)}
                    </span>
                  </li>
                ))}
              </ol>
              {rows.length > HERO_ROWS ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-3 w-full"
                  aria-expanded={expanded}
                  onClick={() =>
                    setOpen((current) => {
                      const next = new Set(current);
                      if (expanded) next.delete(role);
                      else next.add(role);
                      return next;
                    })
                  }
                >
                  {expanded ? <ChevronUp aria-hidden /> : <ChevronDown aria-hidden />}
                  {expanded
                    ? t("stats.heroes.showLess")
                    : t("stats.heroes.showAll", { count: rows.length })}
                </Button>
              ) : null}
            </CardSurface>
          );
        })}
    </div>
  );
}

function clock(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
}

type MapRow = {
  map: CatalogEntityRead;
  mode: string;
  played: number;
  avgDurationSec: number | null;
  picked: number;
  banned: number;
};

/**
 * Every map of the pool in one table: how often it was played and how long it took, how often a team chose it and
 * how often one struck it. A map nobody played stays a row (the pool is the regulation), dimmed.
 */
function MapsTab({ tournament, slug }: Readonly<{ tournament: Tournament; slug: string }>) {
  const t = useTranslations("tournamentDetail");
  const tRoot = useTranslations();
  const mapPool = useTournamentMapPool(tournament.id, tournament.discipline);
  const playedQuery = useQuery(tournamentEncountersQueryOptions(tournament));
  const insights = useTournamentInsights(tournament);
  const bans = useMemo(
    () => aggregateBans(insights.heroBans, insights.mapBans),
    [insights.heroBans, insights.mapBans]
  );

  if (playedQuery.isError || (mapPool.isError && mapPool.pool.total === 0)) {
    return (
      <TournamentPageState
        state="initial-error"
        onRetry={() => {
          mapPool.refetch();
          void playedQuery.refetch();
        }}
      />
    );
  }
  if (mapPool.isPending || !playedQuery.data) return <TournamentMapsSkeleton />;

  const counts = buildMapPlayedCounts(playedQuery.data.results.filter(isEncounterCompleted));
  const choices = new Map((bans?.maps ?? []).map((row) => [row.id, row]));
  const rows: MapRow[] = mapPool.pool.byGamemode.flatMap((group) =>
    group.maps.map((map) => ({
      map,
      mode: group.gamemode,
      played: counts[map.id]?.played ?? 0,
      avgDurationSec: counts[map.id]?.avgDurationSec ?? null,
      picked: choices.get(map.id)?.picked ?? 0,
      banned: choices.get(map.id)?.banned ?? 0
    }))
  );
  if (rows.length === 0) {
    return (
      <TournamentPageState
        state="empty"
        title={tRoot("tournamentDetail.stats.maps.emptyTitle")}
        description={tRoot("tournamentDetail.stats.maps.emptyDescription")}
      />
    );
  }
  const mostPlayed = Math.max(1, ...rows.map((row) => row.played));
  const quiet = (row: MapRow, value: React.ReactNode) =>
    row.played === 0 ? <span className="text-[color:var(--aqt-fg-faint)]">{value}</span> : value;

  const columns: SortableColumn<MapRow>[] = [
    {
      key: "map",
      label: tRoot("tournamentDetail.mapPool.col.map"),
      ascendingFirst: true,
      sortValue: (row) => row.map.name.toLowerCase(),
      cell: (row) => (
        <span className="flex min-w-0 items-center gap-3">
          <span className="relative hidden aspect-video w-16 shrink-0 overflow-hidden rounded border border-[color:var(--aqt-border)] sm:block">
            {row.map.image_path ? (
              <Image src={row.map.image_path} alt="" fill sizes="64px" className="object-cover" />
            ) : (
              <span className="grid h-full place-items-center text-[color:var(--aqt-fg-faint)]">
                <ImageOff aria-hidden width={12} height={12} />
              </span>
            )}
          </span>
          <span className="flex min-w-0 flex-col">
            {row.played > 0 ? (
              <Link
                href={tournamentHref({ slug }, `/matches?map=${row.map.id}`)}
                className="truncate text-caption font-semibold hover:text-[color:var(--aqt-teal)]"
              >
                {row.map.name}
              </Link>
            ) : (
              <span className="truncate text-caption text-[color:var(--aqt-fg-dim)]">
                {row.map.name}
              </span>
            )}
            <span className="flex items-center gap-1.5 text-label text-[color:var(--aqt-fg-dim)]">
              {row.map.parent?.image_path ? (
                <Image src={row.map.parent.image_path} alt="" width={12} height={12} aria-hidden />
              ) : null}
              {row.mode}
            </span>
          </span>
        </span>
      )
    },
    {
      key: "played",
      label: tRoot("tournamentDetail.mapPool.col.played"),
      numeric: true,
      sortValue: (row) => row.played,
      cell: (row) => (
        <span className="flex items-center justify-end gap-3">
          <span
            aria-hidden
            className="hidden h-1.5 w-32 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)] md:block"
          >
            <span
              className="block h-full rounded-full bg-[color:var(--aqt-teal)]"
              style={{ width: `${(row.played / mostPlayed) * 100}%` }}
            />
          </span>
          <span className="w-6 font-semibold">{quiet(row, row.played)}</span>
        </span>
      )
    },
    {
      key: "picked",
      label: t("stats.maps.picked"),
      title: t("stats.maps.pickedTitle"),
      numeric: true,
      sortValue: (row) => row.picked,
      cell: (row) => quiet(row, row.picked)
    },
    {
      key: "banned",
      label: t("stats.maps.banned"),
      title: t("stats.maps.bannedTitle"),
      numeric: true,
      sortValue: (row) => row.banned,
      cell: (row) => quiet(row, row.banned)
    },
    {
      key: "duration",
      label: tRoot("tournamentDetail.mapPool.col.avgDuration"),
      numeric: true,
      sortValue: (row) => row.avgDurationSec,
      cell: (row) => quiet(row, row.avgDurationSec != null ? clock(row.avgDurationSec) : "—")
    }
  ];

  return (
    <CardSurface title={t("stats.maps.table")} flush>
      <SortableTable
        rows={rows}
        columns={columns}
        rowKey={(row) => row.map.id}
        stickyFirst
        defaultSort={{ key: "played", ascending: false }}
        label={t("stats.maps.table")}
        empty={tRoot("tournamentDetail.stats.maps.emptyTitle")}
      />
    </CardSurface>
  );
}
