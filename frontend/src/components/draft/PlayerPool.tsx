"use client";

import { useMemo, useState, type CSSProperties } from "react";
import { Check, Search } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Avatar, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  draftSummary,
  poolRoleColumns,
  roleMarket,
  type PlayerFit,
  type QueueControls,
  type RoomSelection,
  type TeamView
} from "@/lib/draft/room-model";
import {
  allPlayerHeroes,
  DRAFT_POOL_TABS,
  type DraftPoolRoleFilter,
  type DraftPoolTab,
  type DraftPoolView,
  type DraftViewParams
} from "@/lib/draft/workspace-model";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type { DraftBoard, DraftPickOptionsResponse, DraftRole } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { getHeroIconUrl } from "@/utils/player";

import { POOL_GRID, PoolRow, teal, tint } from "./pool/PoolRow";

interface PlayerPoolProps {
  board: DraftBoard;
  pool: DraftPoolView;
  viewParams: DraftViewParams;
  onViewParamsChange: (patch: Partial<DraftViewParams>) => void;
  teamViews: ReadonlyMap<number, TeamView>;
  /** Team the viewer selects for; null → read-only rows and the "Спрос" (demand) column. */
  actingTeam: TeamView | null;
  selection: RoomSelection | null;
  profileId: number | null;
  onSelect: (playerId: number, role: DraftRole) => void;
  onOpenProfile: (playerId: number) => void;
  queue: QueueControls | null;
  /** fitByPlayer for the acting team; null while unavailable. */
  fit: ReadonlyMap<number, PlayerFit> | null;
  /** Server safety for the current pick; only meaningful when `safetyRequired`. */
  options: DraftPickOptionsResponse | null;
  safetyRequired: boolean;
  divisionGrid: DivisionGrid;
  headingId: string;
  /** px of bottom padding for the list so the floating layer never hides the last rows. */
  bottomInset: number;
}

const FOCUS_RING = "outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]";

export function PlayerPool({
  board,
  pool,
  viewParams,
  onViewParamsChange,
  teamViews,
  actingTeam,
  selection,
  profileId,
  onSelect,
  onOpenProfile,
  queue,
  fit,
  options,
  safetyRequired,
  divisionGrid,
  headingId,
  bottomInset
}: Readonly<PlayerPoolProps>) {
  const t = useTranslations("draftRedesign");
  const [heroFilter, setHeroFilter] = useState<ReadonlySet<string>>(() => new Set());
  const { session } = board;
  const tab = viewParams.pool;
  const queueEditable = queue != null && session.status !== "completed" && session.status !== "cancelled";

  const columns = useMemo(
    () => poolRoleColumns(session.roster_shape, board.players),
    [session.roster_shape, board.players]
  );
  const market = useMemo(() => roleMarket(board, teamViews), [board, teamViews]);
  const summary = useMemo(
    () => (session.status === "completed" ? draftSummary(board, teamViews) : null),
    [session.status, board, teamViews]
  );
  const heroOptions = useMemo(() => {
    const seen = new Map<string, string | null>();
    for (const player of pool.filtered) {
      for (const hero of allPlayerHeroes(player)) {
        if (!seen.has(hero.slug)) seen.set(hero.slug, hero.imagePath);
      }
    }
    return [...seen]
      .map(([slug, imagePath]) => ({ slug, imagePath }))
      .sort((left, right) => left.slug.localeCompare(right.slug));
  }, [pool.filtered]);
  const rows = useMemo(
    () =>
      heroFilter.size === 0
        ? pool.filtered
        : pool.filtered.filter((player) => allPlayerHeroes(player).some((hero) => heroFilter.has(hero.slug))),
    [pool.filtered, heroFilter]
  );

  const tabCounts: Record<DraftPoolTab, number> = {
    available: pool.available.length,
    shortlist: pool.shortlist.length,
    all: pool.all.length
  };
  const chips: { key: DraftPoolRoleFilter; label: string; count: number; role: DraftRole | null }[] = [
    ...(actingTeam
      ? [
          {
            key: "need" as const,
            label: t("pool.chip.need", { team: actingTeam.team.name }),
            count: pool.needCount ?? 0,
            role: null
          }
        ]
      : []),
    { key: "all", label: t("pool.chip.all"), count: pool.available.length, role: null },
    ...columns.map((role) => ({ key: role, label: t(`roles.${role}`), count: pool.roleCounts[role], role }))
  ];
  const filtersOn = viewParams.role !== "all" || viewParams.query !== "" || heroFilter.size > 0;
  const resetFilters = () => {
    setHeroFilter(new Set());
    onViewParamsChange({ role: "all", query: "" });
  };
  const toggleHero = (slug: string) =>
    setHeroFilter((current) => {
      const next = new Set(current);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });

  return (
    <Tabs
      value={tab}
      onValueChange={(value) => onViewParamsChange({ pool: value as DraftPoolTab })}
      asChild
    >
      <section
        aria-labelledby={headingId}
        className="flex min-w-0 flex-col overflow-clip rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] shadow-[0_1px_2px_rgb(0_0_0/0.25)] xl:h-full"
      >
        <div className="flex flex-col gap-3 border-b border-[color:var(--aqt-border)] px-4 pb-3 pt-3.5">
          <div className="flex flex-wrap items-center gap-3.5">
            <h2 id={headingId} className="font-onest text-base font-semibold leading-snug">
              {t("pool.title")}
            </h2>
            <TabsList
              aria-label={t("pool.tabsLabel")}
              className="h-auto gap-0.5 rounded-[10px] bg-[color:var(--aqt-card-2)] p-[3px]"
            >
              {DRAFT_POOL_TABS.filter((entry) => entry !== "shortlist" || queue != null).map((entry) => (
                <TabsTrigger
                  key={entry}
                  value={entry}
                  className="min-h-11 gap-1.5 rounded-lg px-[11px] py-0 text-caption font-medium text-[color:var(--aqt-fg-muted)] ring-offset-0 focus-visible:ring-[color:var(--aqt-teal)] focus-visible:ring-offset-0 data-[state=active]:bg-[color:var(--aqt-card)] data-[state=active]:text-[color:var(--aqt-fg)] data-[state=active]:shadow-none sm:min-h-[30px]"
                >
                  {t(`pool.tab.${entry}`)}
                  <span className="font-normal tabular-nums text-[color:var(--aqt-fg-faint)]">{tabCounts[entry]}</span>
                </TabsTrigger>
              ))}
            </TabsList>
            <label className="relative ml-auto flex min-w-[180px] flex-[0_1_280px] items-center">
              <span className="sr-only">{t("pool.search")}</span>
              <Search
                className="pointer-events-none absolute left-3 h-4 w-4 text-[color:var(--aqt-fg-faint)]"
                aria-hidden="true"
              />
              <Input
                value={viewParams.query}
                onChange={(event) => onViewParamsChange({ query: event.target.value })}
                placeholder={t("pool.search")}
                className="h-11 rounded-lg border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] pl-9 sm:h-[34px]"
              />
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div role="group" aria-label={t("pool.roleFilter")} className="flex flex-wrap items-center gap-2">
              {chips.map((chip) => {
                const on = viewParams.role === chip.key;
                return (
                  <button
                    key={chip.key}
                    type="button"
                    aria-pressed={on}
                    aria-label={t("pool.chip.aria", { label: chip.label, count: chip.count })}
                    onClick={() => onViewParamsChange({ role: chip.key })}
                    style={
                      {
                        "--chip-bg": on ? (chip.role ? tint(chip.role, 12) : teal(12)) : "transparent",
                        borderColor: on ? (chip.role ? ROLE_ACCENT[chip.role] : "var(--aqt-teal)") : "var(--aqt-border-2)"
                      } as CSSProperties
                    }
                    className={cn(
                      "flex min-h-11 max-w-full items-center gap-1.5 rounded-full border bg-[color:var(--chip-bg)] px-[11px] text-caption font-medium hover:bg-[color:var(--aqt-overlay-3)] sm:min-h-8",
                      FOCUS_RING,
                      on ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-muted)]"
                    )}
                  >
                    {chip.role && (
                      <PlayerRoleIcon
                        role={getRoleIconName(chip.role)}
                        size={17}
                        color={ROLE_ACCENT[chip.role]}
                        decorative
                      />
                    )}
                    <span className="truncate">{chip.label}</span>
                    <span className="font-normal tabular-nums text-[color:var(--aqt-fg-faint)]">{chip.count}</span>
                  </button>
                );
              })}
            </div>
            <div className="ml-auto flex items-center gap-1">
              <span
                id={`${headingId}-sort`}
                className="mr-1 text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-faint)]"
              >
                {t("pool.sortLabel")}
              </span>
              <div role="group" aria-labelledby={`${headingId}-sort`} className="flex items-center gap-1">
                {(["rank", "name"] as const).map((sort) => {
                  const on = viewParams.sort === sort;
                  return (
                    <button
                      key={sort}
                      type="button"
                      aria-pressed={on}
                      onClick={() => onViewParamsChange({ sort })}
                      className={cn(
                        "flex min-h-11 items-center rounded-[7px] px-2.5 text-caption font-medium sm:min-h-7",
                        FOCUS_RING,
                        on
                          ? "bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg)]"
                          : "text-[color:var(--aqt-fg-muted)]"
                      )}
                    >
                      {t(`pool.sort.${sort}`)}
                    </button>
                  );
                })}
              </div>
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={cn(
                      "min-h-11 rounded-[7px] px-2.5 text-caption font-medium sm:min-h-7",
                      heroFilter.size > 0
                        ? "bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg)]"
                        : "text-[color:var(--aqt-fg-muted)]"
                    )}
                    aria-label={t("heroFilterCount", { count: heroFilter.size })}
                  >
                    {t("heroFilter")}
                    {heroFilter.size > 0 && <span className="tabular-nums">{heroFilter.size}</span>}
                  </Button>
                </PopoverTrigger>
                <PopoverContent align="end" className="w-72 p-0">
                  <Command>
                    <CommandInput placeholder={t("heroFilter")} />
                    <CommandList>
                      <CommandEmpty>{t("pool.heroEmpty")}</CommandEmpty>
                      <CommandGroup>
                        {heroOptions.map((hero) => (
                          <CommandItem key={hero.slug} value={hero.slug} onSelect={() => toggleHero(hero.slug)}>
                            <Avatar className="h-5 w-5" title={hero.slug}>
                              <AvatarImage src={getHeroIconUrl(hero.slug, hero.imagePath)} alt={hero.slug} />
                            </Avatar>
                            <span className="truncate capitalize">{hero.slug.replace(/-/g, " ")}</span>
                            <Check
                              className={cn("ml-auto h-4 w-4", heroFilter.has(hero.slug) ? "opacity-100" : "opacity-0")}
                            />
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    </CommandList>
                    {heroFilter.size > 0 && (
                      <div className="border-t border-[color:var(--aqt-border)] p-1">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="min-h-9 w-full"
                          onClick={() => setHeroFilter(new Set())}
                        >
                          {t("heroFilterClear")}
                        </Button>
                      </div>
                    )}
                  </Command>
                </PopoverContent>
              </Popover>
            </div>
          </div>

          {market.length > 0 && (
            <ul
              aria-label={t("pool.market.label")}
              className="grid gap-x-[18px] gap-y-3"
              style={{ gridTemplateColumns: `repeat(auto-fit, minmax(min(100%, 160px), 1fr))` }}
            >
              {market.map((entry) => {
                const supply = entry.primary + entry.secondary;
                const denominator = Math.max(entry.openSlots, supply, 1);
                const barColor = entry.deficit ? "var(--aqt-rose)" : ROLE_ACCENT[entry.role];
                const roleLabel = t(`roles.${entry.role}`);
                const title = `${t("pool.market.title", {
                  role: roleLabel,
                  open: entry.openSlots,
                  primary: entry.primary,
                  secondary: entry.secondary
                })}${entry.deficit ? ` ${t("pool.market.deficit")}` : ""}`;
                return (
                  <li key={entry.role} title={title}>
                    <span className="sr-only">{title}</span>
                    <div className="flex items-center gap-[7px] text-body text-[color:var(--aqt-fg-muted)]" aria-hidden="true">
                      <PlayerRoleIcon role={getRoleIconName(entry.role)} size={17} color={ROLE_ACCENT[entry.role]} decorative />
                      <span className="min-w-0 truncate">
                        {t("pool.market.slots", { role: roleLabel, count: entry.openSlots })}
                      </span>
                      <span
                        className={cn(
                          "ml-auto shrink-0 whitespace-nowrap font-semibold tabular-nums",
                          entry.deficit
                            ? "text-[color:var(--aqt-rose)]"
                            : entry.tight
                              ? "text-[color:var(--aqt-amber)]"
                              : "text-[color:var(--aqt-fg)]"
                        )}
                      >
                        {entry.secondary > 0
                          ? t("pool.market.supplyWithSecondary", {
                              primary: entry.primary,
                              secondary: entry.secondary,
                              total: supply
                            })
                          : t("pool.market.supply", { primary: entry.primary, total: supply })}
                      </span>
                    </div>
                    <div
                      className="mt-[7px] flex h-[5px] overflow-hidden rounded-full bg-[color:var(--aqt-overlay-3)]"
                      aria-hidden="true"
                    >
                      <span style={{ width: `${(entry.primary / denominator) * 100}%`, background: barColor }} />
                      <span
                        style={{
                          width: `${(entry.secondary / denominator) * 100}%`,
                          background: `color-mix(in srgb, ${barColor} 45%, transparent)`
                        }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {summary && (
          <div className="border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-5 py-[18px]">
            <h3 className="font-onest text-lg font-semibold leading-snug">{t("pool.summary.title")}</h3>
            <dl className="mt-3.5 grid grid-cols-2 gap-4 sm:grid-cols-4">
              {[
                {
                  key: "spread" as const,
                  value: summary.spread == null ? "—" : String(Math.round(summary.spread)),
                  sub: t("pool.summary.spreadSub")
                },
                { key: "offRole" as const, value: String(summary.offRole), sub: t("pool.summary.offRoleSub") },
                {
                  key: "autopicks" as const,
                  value: String(summary.autopicks),
                  sub: t("pool.summary.autopicksSub", { total: summary.picks })
                },
                { key: "overrides" as const, value: String(summary.overrides), sub: t("pool.summary.overridesSub") }
              ].map((tile) => (
                <div key={tile.key} className="flex flex-col">
                  <dt className="text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                    {t(`pool.summary.${tile.key}`)}
                  </dt>
                  <dd className="mt-1 font-onest text-[30px] font-bold leading-[1.1] tabular-nums">{tile.value}</dd>
                  <dd className="mt-0.5 text-caption text-[color:var(--aqt-fg-muted)]">{tile.sub}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        <TabsContent
          value={tab}
          className="mt-0 min-h-0 flex-1 ring-offset-0 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)] focus-visible:ring-offset-0 xl:overflow-y-auto"
          style={{ "--pool-roles": `${Math.max(columns.length, 1)}fr`, paddingBottom: bottomInset } as CSSProperties}
        >
          <div
            aria-hidden="true"
            className={cn(
              POOL_GRID,
              "sticky top-0 z-10 hidden border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-4 py-2 text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-faint)] sm:grid"
            )}
          >
            <span>{t("pool.col.player")}</span>
            <span
              className="grid gap-1.5"
              style={{ gridTemplateColumns: `repeat(${Math.max(columns.length, 1)}, minmax(0, 1fr))` }}
            >
              {columns.map((role) => (
                <span key={role} className="flex min-w-0 items-center gap-1.5" style={{ color: ROLE_ACCENT[role] }}>
                  <PlayerRoleIcon role={getRoleIconName(role)} size={16} color={ROLE_ACCENT[role]} decorative />
                  <span className="truncate">{t(`roles.${role}`)}</span>
                </span>
              ))}
            </span>
            <span className="text-right">{actingTeam ? t("pool.col.fit") : t("pool.col.demand")}</span>
            <span />
          </div>

          {rows.length > 0 ? (
            <div role="list" aria-label={t("pool.title")}>
              {rows.map((player) => (
                <PoolRow
                  key={player.id}
                  player={player}
                  columns={columns}
                  tab={tab}
                  roleFilter={viewParams.role}
                  teamViews={teamViews}
                  actingTeam={actingTeam}
                  selectedRole={selection?.playerId === player.id ? selection.role : null}
                  isProfile={profileId === player.id}
                  fit={fit?.get(player.id)}
                  queue={queue}
                  queueEditable={queueEditable}
                  options={options}
                  safetyRequired={safetyRequired}
                  divisionGrid={divisionGrid}
                  idPrefix={headingId}
                  onSelect={onSelect}
                  onOpenProfile={onOpenProfile}
                />
              ))}
            </div>
          ) : (
            <PoolEmpty
              kind={
                // A filter miss offers a reset; an exhausted list must not promise players that do not exist.
                filtersOn && tabCounts[tab] > 0 ? "filtered" : tab === "shortlist" ? "shortlist" : "none"
              }
              onReset={resetFilters}
            />
          )}
        </TabsContent>
      </section>
    </Tabs>
  );
}

function PoolEmpty({ kind, onReset }: Readonly<{ kind: "filtered" | "shortlist" | "none"; onReset: () => void }>) {
  const t = useTranslations("draftRedesign");
  return (
    <div className="px-5 py-14 text-center">
      <p className="text-base font-semibold">{t(`pool.empty.${kind}Title`)}</p>
      <p className="mt-1.5 text-body text-[color:var(--aqt-fg-muted)]">{t(`pool.empty.${kind}Text`)}</p>
      {kind === "filtered" && (
        <Button type="button" variant="outline" className="mt-4 min-h-10" onClick={onReset}>
          {t("resetFilters")}
        </Button>
      )}
    </div>
  );
}
