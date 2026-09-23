"use client";

import { useMemo, useState } from "react";
import { Ban, Check, Crown, Heart, Search, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/divisions/grid";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type {
  DraftPickOptionsResponse,
  DraftPlayer,
  DraftRole,
  DraftTeam
} from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { formatSubRoleLabel, getHeroIconUrl } from "@/utils/player";

import type { DraftPoolRoleFilter, DraftPoolSort, DraftPoolTab } from "@/lib/draft/workspace-model";
import { allPlayerHeroes, DRAFT_POOL_TABS, optionForSelection, playerRoles } from "@/lib/draft/workspace-model";

const POOL_ROLES: DraftRole[] = ["tank", "damage", "support"];
const SEGMENT_CLASS =
  "inline-flex min-h-8 items-center justify-center gap-1 rounded-md px-2.5 text-xs font-medium text-[color:var(--aqt-fg-muted)] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]";
const SEGMENT_ACTIVE = "bg-[color:var(--aqt-card)] text-[color:var(--aqt-fg)]";
const EMPTY_SHORTLIST: ReadonlySet<number> = new Set();
const NO_TEAMS: DraftTeam[] = [];

export interface PoolSelection {
  playerId: number;
  role: DraftRole;
}

interface PlayerPoolProps {
  /** Already filtered + sorted by the caller's view model. */
  players: DraftPlayer[];
  /** How many players the OPEN tab holds before this component's hero filter. */
  totalPlayers: number;
  roleCounts: Record<DraftRole, number>;
  /** Tab sizes for the Available/Shortlist/Drafted chips. */
  poolCounts: Record<DraftPoolTab, number>;
  pool: DraftPoolTab;
  selection?: PoolSelection | null;
  shortlist?: ReadonlySet<number>;
  role: DraftPoolRoleFilter;
  sort: DraftPoolSort;
  query: string;
  options?: DraftPickOptionsResponse | null;
  safetyRequired?: boolean;
  /** Names the drafted tab's team badge. */
  teams?: DraftTeam[];
  /** Omit for spectators: the role buttons then render as plain read-only chips. */
  onSelect?: (player: DraftPlayer, role: DraftRole) => void;
  onOpenProfile: (player: DraftPlayer) => void;
  onToggleShortlist?: (playerId: number) => void;
  onFiltersChange: (
    patch: Partial<{ role: DraftPoolRoleFilter; sort: DraftPoolSort; query: string; pool: DraftPoolTab }>
  ) => void;
  onResetFilters: () => void;
  divisionGrid: DivisionGrid;
  /** Unique per mounted instance: the mobile and desktop trees both render a pool. */
  headingId?: string;
}

export function PlayerPool({
  players,
  totalPlayers,
  roleCounts,
  poolCounts,
  pool,
  selection = null,
  shortlist = EMPTY_SHORTLIST,
  role,
  sort,
  query,
  options = null,
  safetyRequired = false,
  teams = NO_TEAMS,
  onSelect,
  onOpenProfile,
  onToggleShortlist,
  onFiltersChange,
  onResetFilters,
  divisionGrid,
  headingId = "player-pool-heading"
}: Readonly<PlayerPoolProps>) {
  const t = useTranslations("draftRedesign");
  const [heroFilter, setHeroFilter] = useState<Set<string>>(() => new Set());
  const teamNames = useMemo(() => new Map(teams.map((team) => [team.id, team.name])), [teams]);
  const heroOptions = useMemo(() => {
    const seen = new Map<string, string | null>();
    for (const player of players) {
      for (const hero of allPlayerHeroes(player)) {
        if (!seen.has(hero.slug)) seen.set(hero.slug, hero.imagePath);
      }
    }
    return [...seen]
      .map(([slug, imagePath]) => ({ slug, imagePath }))
      .sort((left, right) => left.slug.localeCompare(right.slug));
  }, [players]);
  const visiblePlayers = useMemo(() => {
    if (heroFilter.size === 0) return players;
    return players.filter((player) =>
      allPlayerHeroes(player).some((hero) => heroFilter.has(hero.slug))
    );
  }, [players, heroFilter]);
  const toggleHero = (slug: string) => {
    setHeroFilter((current) => {
      const next = new Set(current);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  };

  const emptyTabMessage =
    pool === "shortlist" ? t("shortlistEmpty") : pool === "drafted" ? t("draftedEmpty") : t("poolExhausted");

  return (
    <section aria-labelledby={headingId}>
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[color:var(--aqt-border)] pb-3">
        <h2 id={headingId} className="font-onest text-lg font-semibold">{t("availablePool")}</h2>
        <span className="text-xs text-[color:var(--aqt-fg-muted)]">{visiblePlayers.length}/{totalPlayers}</span>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-[1fr_auto]">
        <label className="relative">
          <span className="sr-only">{t("searchPlayers")}</span>
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-[color:var(--aqt-fg-faint)]" />
          <Input
            className="pl-9"
            value={query}
            onChange={(event) => onFiltersChange({ query: event.target.value })}
            placeholder={t("searchPlayers")}
          />
        </label>
        <Select value={sort} onValueChange={(value) => onFiltersChange({ sort: value as DraftPoolSort })}>
          <SelectTrigger className="w-full sm:w-32" aria-label={t("sortPool")}><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="rank">{t("sortRank")}</SelectItem>
            <SelectItem value="name">{t("sortName")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <div className="inline-flex min-w-0 flex-wrap gap-0.5 rounded-lg bg-[color:var(--aqt-card-2)] p-0.5" role="group" aria-label={t("filterRole")}>
          <button
            type="button"
            aria-pressed={role === "all"}
            onClick={() => onFiltersChange({ role: "all" })}
            className={cn(SEGMENT_CLASS, role === "all" && SEGMENT_ACTIVE)}
          >
            {t("allRoles")}
          </button>
          {POOL_ROLES.map((entry) => (
            <button
              key={entry}
              type="button"
              aria-pressed={role === entry}
              onClick={() => onFiltersChange({ role: entry })}
              className={cn(SEGMENT_CLASS, role === entry && SEGMENT_ACTIVE)}
            >
              <PlayerRoleIcon role={getRoleIconName(entry)} size={16} color={ROLE_ACCENT[entry]} decorative />
              <span className="sr-only">{t(`roles.${entry}`)}</span>
              <span className="tabular-nums">{roleCounts[entry]}</span>
            </button>
          ))}
        </div>
        {/* Which LIST the rows come from, beside which role narrows it: the
            shortlist and the drafted are the same players, read two other ways. */}
        <div className="inline-flex min-w-0 flex-wrap gap-0.5 rounded-lg bg-[color:var(--aqt-card-2)] p-0.5" role="group" aria-label={t("filterPool")}>
          {DRAFT_POOL_TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              aria-pressed={pool === tab}
              onClick={() => onFiltersChange({ pool: tab })}
              className={cn(SEGMENT_CLASS, pool === tab && SEGMENT_ACTIVE)}
            >
              {t(`poolTab.${tab}`, { count: poolCounts[tab] })}
            </button>
          ))}
        </div>
        <Popover>
          <PopoverTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="ml-auto min-h-8 gap-1.5"
              aria-label={t("heroFilterCount", { count: heroFilter.size })}
            >
              {t("heroFilter")} ({heroFilter.size})
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-72 p-0">
            <Command>
              <CommandInput placeholder={t("heroFilter")} />
              <CommandList>
                <CommandEmpty>{t("noFilterResults")}</CommandEmpty>
                <CommandGroup>
                  {heroOptions.map((hero) => {
                    const checked = heroFilter.has(hero.slug);
                    return (
                      <CommandItem key={hero.slug} value={hero.slug} onSelect={() => toggleHero(hero.slug)}>
                        <Avatar className="h-5 w-5" title={hero.slug}>
                          <AvatarImage src={getHeroIconUrl(hero.slug, hero.imagePath)} alt={hero.slug} />
                        </Avatar>
                        <span className="truncate capitalize">{hero.slug.replace(/-/g, " ")}</span>
                        <Check className={cn("ml-auto h-4 w-4", checked ? "opacity-100" : "opacity-0")} />
                      </CommandItem>
                    );
                  })}
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

      {totalPlayers === 0 ? (
        // An exhausted tab is not a filter miss: offering "reset filters"
        // here promises players that no longer exist.
        <p className="py-12 text-center text-sm text-[color:var(--aqt-fg-muted)]">{emptyTabMessage}</p>
      ) : visiblePlayers.length === 0 ? (
        <div className="py-12 text-center">
          <Search className="mx-auto h-7 w-7 text-[color:var(--aqt-fg-faint)]" />
          <p className="mt-3 font-medium">{t("noFilterResults")}</p>
          <p className="mt-1 text-sm text-[color:var(--aqt-fg-muted)]">{t("noFilterResultsHint")}</p>
          <Button
            variant="link"
            className="mt-2 min-h-11"
            onClick={() => {
              setHeroFilter(new Set());
              onResetFilters();
            }}
          >
            {t("resetFilters")}
          </Button>
        </div>
      ) : (
        <ul className="mt-3 divide-y divide-[color:var(--aqt-border)]">
          {visiblePlayers.map((player) => (
            <PoolRow
              key={player.id}
              player={player}
              pool={pool}
              selection={selection}
              shortlisted={shortlist.has(player.id)}
              options={options}
              safetyRequired={safetyRequired}
              teamName={player.drafted_by_team_id == null ? null : teamNames.get(player.drafted_by_team_id) ?? null}
              onSelect={onSelect}
              onOpenProfile={onOpenProfile}
              onToggleShortlist={onToggleShortlist}
              divisionGrid={divisionGrid}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * One dense pool row: the picking controls ARE the row. Every role the server
 * would accept is its own button carrying that role's own rank, so choosing a
 * player and the role to spend them on is a single click instead of a card
 * selection followed by a role picker in a side panel.
 */
function PoolRow({
  player,
  pool,
  selection,
  shortlisted,
  options,
  safetyRequired,
  teamName,
  onSelect,
  onOpenProfile,
  onToggleShortlist,
  divisionGrid
}: Readonly<{
  player: DraftPlayer;
  pool: DraftPoolTab;
  selection: PoolSelection | null;
  shortlisted: boolean;
  options: DraftPickOptionsResponse | null;
  safetyRequired: boolean;
  teamName: string | null;
  onSelect?: (player: DraftPlayer, role: DraftRole) => void;
  onOpenProfile: (player: DraftPlayer) => void;
  onToggleShortlist?: (playerId: number) => void;
  divisionGrid: DivisionGrid;
}>) {
  const t = useTranslations("draftRedesign");
  const name = player.battle_tag ?? `#${player.id}`;
  const roles = playerRoles(player);
  const isSelectedPlayer = selection?.playerId === player.id;
  const division = resolveDivisionFromRank(divisionGrid, player.effective_rank);
  const divisionTitle = [
    division == null ? null : getDivisionLabel(divisionGrid, division),
    player.effective_rank ? `${player.effective_rank} SR` : null
  ].filter(Boolean).join(" · ");
  // Every role unsafe: the row itself is unpickable this turn, which the role
  // buttons each repeat with their own reason.
  const blocked =
    safetyRequired &&
    roles.length > 0 &&
    roles.every((role) => !(optionForSelection(options, player.id, role)?.is_safe ?? false));

  return (
    <li
      className={cn(
        "grid min-h-12 grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1 border-l-2 border-transparent py-1.5 pl-2",
        isSelectedPlayer && "border-l-[color:var(--aqt-teal)] bg-[color:var(--aqt-teal)]/10"
      )}
    >
      <span className="inline-flex h-7 w-7 items-center justify-center" title={divisionTitle}>
        {division != null ? (
          <DivisionIcon division={division} tournamentGrid={divisionGrid} width={28} height={28} className="h-7 w-7 object-contain" />
        ) : (
          <span className="text-[color:var(--aqt-fg-faint)]">—</span>
        )}
      </span>

      <span className="col-span-2 flex min-w-0 flex-wrap items-center gap-x-1.5 sm:col-span-1">
        {/* The name is the profile trigger, not the pick target: picking is
            what the role buttons on the right are for. */}
        <button
          type="button"
          onClick={() => onOpenProfile(player)}
          aria-label={t("openProfile", { player: name })}
          className={cn(
            "min-w-0 truncate rounded font-medium outline-none hover:text-[color:var(--aqt-teal)] hover:underline focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
            blocked && "text-[color:var(--aqt-fg-dim)]"
          )}
        >
          {name}
        </button>
        {player.is_captain && (
          <Crown className="h-3.5 w-3.5 shrink-0 text-[color:var(--aqt-warm)]" role="img" aria-label={t("captain")} />
        )}
        {player.sub_role && (
          <span className="truncate text-label uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
            {formatSubRoleLabel(player.sub_role)}
          </span>
        )}
        {player.is_flex && (
          <span className="rounded border border-[color:var(--aqt-border-2)] px-1 text-label uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
            {t("flex")}
          </span>
        )}
        {roles.length === 0 && (
          <span className="rounded border border-[color:var(--aqt-border-2)] px-1 text-label uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
            {t("noRole")}
          </span>
        )}
        {blocked ? (
          <Ban className="h-4 w-4 shrink-0 text-[color:var(--aqt-live)]" role="img" aria-label={t("unsafePlayerReason")} />
        ) : safetyRequired ? (
          <ShieldCheck className="h-4 w-4 shrink-0 text-[color:var(--aqt-support)]" role="img" aria-label={t("safeOption")} />
        ) : null}
      </span>

      {/* Phone widths: the role buttons take their own line under the name
          instead of squeezing it to one letter. */}
      <span className="col-span-2 col-start-2 flex min-w-0 flex-wrap items-center gap-1 sm:col-span-1 sm:col-start-auto sm:shrink-0 sm:flex-nowrap sm:justify-end">
        {pool === "drafted" ? (
          <span className="max-w-[12rem] truncate rounded-md border border-[color:var(--aqt-border-2)] px-2 py-1 text-xs text-[color:var(--aqt-fg-muted)]">
            {teamName ?? t("unknownTeam")}
          </span>
        ) : (
          roles.map((role) => (
            <RoleOption
              key={role}
              player={player}
              role={role}
              selected={isSelectedPlayer && selection?.role === role}
              options={options}
              safetyRequired={safetyRequired}
              onSelect={onSelect}
              divisionGrid={divisionGrid}
            />
          ))
        )}
        {onToggleShortlist ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-9 w-9"
            onClick={() => onToggleShortlist(player.id)}
            aria-pressed={shortlisted}
            aria-label={shortlisted ? t("removeShortlist") : t("addShortlist")}
          >
            <Heart className={cn("h-4 w-4", shortlisted && "fill-current text-[color:var(--aqt-teal)]")} />
          </Button>
        ) : null}
      </span>
    </li>
  );
}

function RoleOption({
  player,
  role,
  selected,
  options,
  safetyRequired,
  onSelect,
  divisionGrid
}: Readonly<{
  player: DraftPlayer;
  role: DraftRole;
  selected: boolean;
  options: DraftPickOptionsResponse | null;
  safetyRequired: boolean;
  onSelect?: (player: DraftPlayer, role: DraftRole) => void;
  divisionGrid: DivisionGrid;
}>) {
  const t = useTranslations("draftRedesign");
  const option = optionForSelection(options, player.id, role);
  const unsafe = safetyRequired && !(option?.is_safe ?? false);
  const reason = !unsafe
    ? undefined
    : option?.reason_code === "slot_filled" || option?.reason_code === "role_shortage"
      ? t(`optionReason.${option.reason_code}`)
      : t("unsafeOption");
  // The role's OWN rank, not `effective_rank`: spending a support main on tank
  // is a different number, and that number is the whole decision.
  const rank = player.role_ranks[role] ?? null;
  const division = resolveDivisionFromRank(divisionGrid, rank);
  const content = (
    <>
      <PlayerRoleIcon role={getRoleIconName(role)} size={16} color={ROLE_ACCENT[role]} decorative />
      <span className="tabular-nums">{rank ?? "—"}</span>
      {division != null && (
        <DivisionIcon division={division} tournamentGrid={divisionGrid} width={18} height={18} className="h-[18px] w-[18px] object-contain" />
      )}
    </>
  );
  const shell =
    "inline-flex min-h-9 items-center gap-1 rounded-md border px-1.5 text-xs tabular-nums transition-colors";

  if (!onSelect) {
    // Spectator: the same information, with nothing to press.
    return (
      <span
        className={cn(shell, "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-muted)]")}
        title={t(`roles.${role}`)}
      >
        {content}
      </span>
    );
  }

  return (
    <button
      type="button"
      aria-label={t("pickAs", { player: player.battle_tag ?? `#${player.id}`, role: t(`roles.${role}`) })}
      aria-pressed={selected}
      aria-disabled={unsafe}
      title={reason}
      onClick={() => onSelect(player, role)}
      className={cn(
        shell,
        "outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
        selected
          ? "border-[color:var(--aqt-teal)] bg-[color:var(--aqt-teal)]/15 text-[color:var(--aqt-fg)]"
          : "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-muted)] hover:border-[color:var(--aqt-teal)]/60",
        unsafe && "border-dashed opacity-60"
      )}
    >
      {content}
    </button>
  );
}
