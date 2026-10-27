"use client";

import { useMemo, useRef, useState, type CSSProperties } from "react";
import { AlertCircle, AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Combobox, ComboboxCheck } from "@/components/ui/combobox";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { SearchField } from "@/components/ui/search-field";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
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
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { tint } from "@/lib/colors";
import { roleTint, showsRoles, slotCodeOrder, type RoleOntology } from "@/lib/roster/ontology";
import { cn } from "@/lib/utils";
import type { DraftBoard, DraftPickOptionsResponse, DraftRole } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { getHeroIconUrl } from "@/lib/player";

import { POOL_GRID, PoolRow } from "./pool/PoolRow";

interface PlayerPoolProps {
  board: DraftBoard;
  pool: DraftPoolView;
  viewParams: DraftViewParams;
  onViewParamsChange: (patch: Partial<DraftViewParams>) => void;
  teamViews: ReadonlyMap<number, TeamView>;
  /** Team the viewer selects for; null → read-only rows and no fit column. */
  actingTeam: TeamView | null;
  selection: RoomSelection | null;
  profileId: number | null;
  onSelect: (playerId: number, role: DraftRole) => void;
  onOpenProfile: (playerId: number) => void;
  /** Warms a player's card before a click opens it; `null` cancels. */
  onPrefetchCard: (userId: number | null) => void;
  queue: QueueControls | null;
  /** fitByPlayer for the acting team; null while unavailable. */
  fit: ReadonlyMap<number, PlayerFit> | null;
  /** Server safety for the current pick; only meaningful when `safetyRequired`. */
  options: DraftPickOptionsResponse | null;
  safetyRequired: boolean;
  divisionGrid: DivisionGrid;
  /** The session owner's role dictionary: names, glyphs and colours of every role chip, column and market bar. */
  ontology: RoleOntology | null;
  headingId: string;
  /** px of bottom padding for the list so the floating layer never hides the last rows. */
  bottomInset: number;
}

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
  onPrefetchCard,
  queue,
  fit,
  options,
  safetyRequired,
  divisionGrid,
  ontology,
  headingId,
  bottomInset
}: Readonly<PlayerPoolProps>) {
  const t = useTranslations("draftRedesign");
  const slotLabel = useSlotLabel(ontology);
  // A one-role game keeps its rank column (the cell is the pick) but no role chip, role strip or role head.
  const named = showsRoles(ontology);
  const [heroFilter, setHeroFilter] = useState<ReadonlySet<string>>(() => new Set());
  // Uncontrolled: the URL is written asynchronously, so an input bound to it
  // snaps back to the last committed query on every keystroke and eats both the
  // characters typed in between and every space (the URL keeps it trimmed).
  const searchRef = useRef<HTMLInputElement>(null);
  const { session } = board;
  const tab = viewParams.pool;
  const finished = session.status === "completed";
  const queueEditable = queue != null && !finished && session.status !== "cancelled";

  const columns = useMemo(
    () => poolRoleColumns(session.roster_shape, board.players, slotCodeOrder(ontology)),
    [session.roster_shape, board.players, ontology]
  );
  const market = useMemo(() => (named ? roleMarket(board, teamViews) : []), [named, board, teamViews]);
  const summary = useMemo(
    () => (finished ? draftSummary(board, teamViews) : null),
    [finished, board, teamViews]
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
  // Counts answer "who is left per role"; once the draft is over nobody is, and the chips are plain filters.
  const chips: { key: DraftPoolRoleFilter; label: string; count: number | null; role: DraftRole | null }[] = [
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
    { key: "all", label: t("pool.chip.all"), count: finished ? null : pool.available.length, role: null },
    ...(named
      ? columns.map((role) => ({
          key: role,
          label: slotLabel(role),
          count: finished ? null : (pool.roleCounts[role] ?? 0),
          role
        }))
      : [])
  ];
  const filtersOn = viewParams.role !== "all" || viewParams.query !== "" || heroFilter.size > 0;
  const resetFilters = () => {
    setHeroFilter(new Set());
    if (searchRef.current) searchRef.current.value = "";
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
      <Card asChild className="flex min-w-0 flex-col overflow-clip xl:h-full">
        <section aria-labelledby={headingId}>
          <div className="flex flex-col gap-3 border-b border-[color:var(--aqt-border)] px-4 pb-3 pt-3.5">
            <div className="flex flex-wrap items-center gap-3.5">
              <h2 id={headingId} className="font-onest text-heading font-semibold">
                {t("pool.title")}
              </h2>
              <SearchField
                ref={searchRef}
                label={t("pool.search")}
                defaultValue={viewParams.query}
                onChange={(event) => onViewParamsChange({ query: event.target.value })}
                placeholder={t("pool.search")}
                containerClassName="ml-auto min-w-[180px] flex-[0_1_280px]"
                className="max-sm:h-11"
              />
            </div>
            <TabsList aria-label={t("pool.tabsLabel")}>
              {DRAFT_POOL_TABS.filter((entry) =>
                // A finished draft has nobody available and nothing left to queue: only everyone remains.
                finished ? entry === "all" : entry !== "shortlist" || queue != null
              ).map((entry) => (
                <TabsTrigger key={entry} value={entry} badge={tabCounts[entry]} className="max-sm:h-11">
                  {t(`pool.tab.${entry}`)}
                </TabsTrigger>
              ))}
            </TabsList>

            <div className="flex flex-wrap items-center gap-2">
              <FilterChipGroup label={t("pool.roleFilter")}>
                {chips.map((chip) => (
                  <FilterChip
                    key={chip.key}
                    active={viewParams.role === chip.key}
                    accent={chip.role ? roleTint(ontology, chip.role) : undefined}
                    aria-label={
                      chip.count == null ? undefined : t("pool.chip.aria", { label: chip.label, count: chip.count })
                    }
                    count={chip.count}
                    onClick={() => onViewParamsChange({ role: chip.key })}
                    className="min-h-11 max-w-full sm:min-h-8"
                  >
                    {chip.role && <PlayerRoleIcon role={chip.role} ontology={ontology} size={17} decorative />}
                    <span className="truncate">{chip.label}</span>
                  </FilterChip>
                ))}
              </FilterChipGroup>
              <div className="ml-auto flex items-center gap-1">
                <span id={`${headingId}-sort`} className="mr-1 text-label font-medium text-[color:var(--aqt-fg-faint)]">
                  {t("pool.sortLabel")}
                </span>
                <ToggleGroup
                  variant="pill"
                  size="sm"
                  value={viewParams.sort}
                  onValueChange={(sort) => onViewParamsChange({ sort: sort as DraftViewParams["sort"] })}
                  aria-labelledby={`${headingId}-sort`}
                >
                  {(["rank", "name"] as const).map((sort) => (
                    <ToggleGroupItem key={sort} value={sort} className="min-h-11 sm:min-h-0">
                      {t(`pool.sort.${sort}`)}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
                {/* Uncontrolled: it stays open while heroes are toggled. */}
                <Combobox
                  trigger={
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className={cn(
                        "min-h-11 rounded-[7px] px-2.5 sm:min-h-7",
                        heroFilter.size > 0
                          ? "bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg)]"
                          : "text-[color:var(--aqt-fg-muted)]"
                      )}
                    >
                      {t("heroFilter")}
                      {heroFilter.size > 0 && <span className="tabular-nums">{heroFilter.size}</span>}
                    </Button>
                  }
                  align="end"
                  searchPlaceholder={t("heroFilter")}
                  emptyMessage={t("pool.heroEmpty")}
                  clear={
                    heroFilter.size > 0
                      ? { label: t("heroFilterClear"), value: "__clear__", onSelect: () => setHeroFilter(new Set()) }
                      : undefined
                  }
                >
                  <CommandGroup>
                    {heroOptions.map((hero) => (
                      <CommandItem key={hero.slug} value={hero.slug} onSelect={() => toggleHero(hero.slug)}>
                        <CatalogEntityImage
                          entity={{ name: hero.slug, image_path: getHeroIconUrl(hero.slug, hero.imagePath) }}
                          size={20}
                          decorative
                        />
                        <span className="min-w-0 flex-1 truncate capitalize">{hero.slug.replace(/-/g, " ")}</span>
                        {/* cmdk's aria-selected follows the highlighted row, not the
                            filter, so the filter state is spelled out. */}
                        {heroFilter.has(hero.slug) && <span className="sr-only">{t("heroFilterOn")}</span>}
                        <ComboboxCheck selected={heroFilter.has(hero.slug)} />
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </Combobox>
              </div>
            </div>

            {market.length > 0 && !finished && (
              <ul
                aria-label={t("pool.market.label")}
                className="grid gap-x-[18px] gap-y-3"
                style={{ gridTemplateColumns: `repeat(auto-fit, minmax(min(100%, 200px), 1fr))` }}
              >
                {market.map((entry) => {
                  const supply = entry.primary + entry.secondary;
                  const denominator = Math.max(entry.openSlots, supply, 1);
                  const barColor = entry.deficit ? "var(--aqt-rose)" : roleTint(ontology, entry.role);
                  const roleLabel = slotLabel(entry.role);
                  // Shortage is a fact, not a hue: the icon + word carry it, the colour only repeats it.
                  const shortage = entry.deficit ? "deficit" : entry.tight ? "tight" : null;
                  const ShortageIcon = entry.deficit ? AlertTriangle : AlertCircle;
                  const title = `${t("pool.market.title", {
                    role: roleLabel,
                    open: entry.openSlots,
                    primary: entry.primary,
                    secondary: entry.secondary
                  })}${shortage ? ` ${t(`pool.market.${shortage}`)}` : ""}`;
                  return (
                    <li key={entry.role} title={title}>
                      <span className="sr-only">{title}</span>
                      <div
                        className="flex flex-wrap items-center gap-x-[7px] gap-y-0.5 text-body text-[color:var(--aqt-fg-muted)]"
                        aria-hidden="true"
                      >
                        <PlayerRoleIcon role={entry.role} ontology={ontology} size={17} decorative />
                        <span className="min-w-0 truncate">{roleLabel}</span>
                        <span className="shrink-0 whitespace-nowrap tabular-nums">
                          {t("pool.market.slots", { count: entry.openSlots })}
                        </span>
                        {shortage && (
                          <span
                            className={cn(
                              "flex shrink-0 items-center gap-1 font-medium",
                              entry.deficit ? "text-[color:var(--aqt-rose-text)]" : "text-[color:var(--aqt-amber)]"
                            )}
                          >
                            <ShortageIcon className="h-[15px] w-[15px]" aria-hidden="true" />
                            {t(`pool.market.${shortage}Label`)}
                          </span>
                        )}
                        <span
                          className={cn(
                            "ml-auto shrink-0 whitespace-nowrap font-semibold tabular-nums",
                            entry.deficit
                              ? "text-[color:var(--aqt-rose-text)]"
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
                            background: tint(barColor, 45)
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
              <h3 className="font-onest text-ui font-semibold">{t("pool.summary.title")}</h3>
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
                    <dt className="text-label font-medium text-[color:var(--aqt-fg-faint)]">
                      {t(`pool.summary.${tile.key}`)}
                    </dt>
                    <dd className="mt-1 font-onest text-headline font-bold tabular-nums">{tile.value}</dd>
                    <dd className="mt-0.5 text-caption text-[color:var(--aqt-fg-muted)]">{tile.sub}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          <TabsContent
            value={tab}
            className="mt-0 min-h-0 flex-1 ring-offset-0 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)] focus-visible:ring-offset-0 xl:scroll-pb-[var(--draft-layer-h,0px)] xl:overflow-y-auto"
            style={{ "--pool-roles": `${Math.max(columns.length, 1)}fr`, paddingBottom: bottomInset } as CSSProperties}
          >
            <div
              aria-hidden="true"
              className={cn(
                POOL_GRID,
                eyebrowClass("muted"),
                "sticky top-[var(--draft-tabs-h,0px)] z-10 hidden border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-4 py-2 sm:grid"
              )}
            >
              <span>{t("pool.col.player")}</span>
              <span
                className="grid gap-1.5"
                style={{ gridTemplateColumns: `repeat(${Math.max(columns.length, 1)}, minmax(0, 1fr))` }}
              >
                {named && columns.map((role) => (
                  <span key={role} className="flex min-w-0 items-center gap-1.5" style={{ color: roleTint(ontology, role) }}>
                    <PlayerRoleIcon role={role} ontology={ontology} size={16} decorative />
                    <span className="truncate">{slotLabel(role)}</span>
                  </span>
                ))}
              </span>
              <span className="text-right">{actingTeam && t("pool.col.fit")}</span>
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
                    ontology={ontology}
                    idPrefix={headingId}
                    onSelect={onSelect}
                    onOpenProfile={onOpenProfile}
                    onPrefetchCard={onPrefetchCard}
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
      </Card>
    </Tabs>
  );
}

function PoolEmpty({ kind, onReset }: Readonly<{ kind: "filtered" | "shortlist" | "none"; onReset: () => void }>) {
  const t = useTranslations("draftRedesign");
  return (
    <div className="px-5 py-14 text-center">
      <p className="text-ui font-semibold">{t(`pool.empty.${kind}Title`)}</p>
      <p className="mt-1.5 text-body text-[color:var(--aqt-fg-muted)]">{t(`pool.empty.${kind}Text`)}</p>
      {kind === "filtered" && (
        <Button type="button" variant="outline" className="mt-4 min-h-10" onClick={onReset}>
          {t("resetFilters")}
        </Button>
      )}
    </div>
  );
}
