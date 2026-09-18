"use client";

import { useMemo, useState } from "react";
import { Ban, Bookmark, BookmarkCheck, Check, Search, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Avatar, AvatarImage, AvatarStack } from "@/components/ui/avatar";
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
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/division-grid";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { DraftPickOptionsResponse, DraftPlayer, DraftRole } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { formatSubRoleLabel, getHeroIconUrl, getPlayerSlug } from "@/utils/player";

import type { DraftPoolRoleFilter, DraftPoolSort } from "@/lib/draft-workspace-model";
import { allPlayerHeroes, playerRoles, roleTopHeroes, safeRoleForPlayer } from "@/lib/draft-workspace-model";

const POOL_ROLES: DraftRole[] = ["tank", "damage", "support"];
const SEGMENT_CLASS =
  "inline-flex min-h-8 items-center justify-center gap-1 rounded-md px-2.5 text-xs font-medium text-[color:var(--aqt-fg-muted)] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]";
const SEGMENT_ACTIVE = "bg-[color:var(--aqt-card)] text-[color:var(--aqt-fg)]";

interface PlayerPoolProps {
  players: DraftPlayer[];
  totalPlayers: number;
  roleCounts: Record<DraftRole, number>;
  selectedPlayerId: number | null;
  shortlist: ReadonlySet<number>;
  role: DraftPoolRoleFilter;
  sort: DraftPoolSort;
  query: string;
  options: DraftPickOptionsResponse | null;
  safetyRequired: boolean;
  onSelect: (player: DraftPlayer, role: DraftRole | null) => void;
  onToggleShortlist: (playerId: number) => void;
  onFiltersChange: (patch: Partial<{ role: DraftPoolRoleFilter; sort: DraftPoolSort; query: string }>) => void;
  onResetFilters: () => void;
  divisionGrid: DivisionGrid;
  /** Unique per mounted instance: the mobile and desktop trees both render a pool. */
  headingId?: string;
}

export function PlayerPool({
  players,
  totalPlayers,
  roleCounts,
  selectedPlayerId,
  shortlist,
  role,
  sort,
  query,
  options,
  safetyRequired,
  onSelect,
  onToggleShortlist,
  onFiltersChange,
  onResetFilters,
  divisionGrid,
  headingId = "player-pool-heading"
}: Readonly<PlayerPoolProps>) {
  const t = useTranslations("draftRedesign");
  const [heroFilter, setHeroFilter] = useState<Set<string>>(() => new Set());
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

      {visiblePlayers.length === 0 ? (
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
        <div className="mt-4 grid gap-x-6 grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3">
          {visiblePlayers.map((player) => {
            const roles = playerRoles(player);
            const secondaryRoles = roles.filter((entry) => entry !== player.primary_role);
            // The server lists options in its own role order (tank, damage,
            // support), so taking its first safe one preselected a secondary
            // role for anybody whose primary sorts later. Ask in the player's
            // own order instead.
            const safeRole = safeRoleForPlayer(options, player);
            const blocked = safetyRequired && safeRole == null;
            const bookmarked = shortlist.has(player.id);
            const isSelected = selectedPlayerId === player.id;
            // `effective_rank` is the server's one rank for this player in this
            // draft, resolved by the roster engine.
            const division = resolveDivisionFromRank(divisionGrid, player.effective_rank);
            const divisionTitle = [
              getDivisionLabel(divisionGrid, division),
              player.effective_rank ? `${player.effective_rank} SR` : null
            ].filter(Boolean).join(" · ");
            const primaryRole = player.primary_role;
            const heroes = primaryRole ? roleTopHeroes(player, primaryRole) : [];
            const profileSlug = player.battle_tag ? getPlayerSlug(player.battle_tag) : null;
            const selectPlayer = () => onSelect(player, safeRole ?? roles[0] ?? null);
            return (
              <article
                key={player.id}
                className={cn(
                  "group relative grid min-h-[64px] grid-cols-[1fr_auto] items-center gap-3 border-b border-l-2 border-[color:var(--aqt-border)] py-2.5 pl-3",
                  isSelected && "bg-[color:var(--aqt-teal)]/10"
                )}
                style={{ borderLeftColor: isSelected && primaryRole ? ROLE_ACCENT[primaryRole] : "transparent" }}
              >
                {/* Full-row select target. A real button with a short name, so the
                    profile link below is a sibling instead of nested interactive
                    content that would swallow the accessible name. */}
                <button
                  type="button"
                  onClick={selectPlayer}
                  aria-pressed={isSelected}
                  aria-label={t("selectPlayer", { player: player.battle_tag ?? `#${player.id}` })}
                  className="absolute inset-0 z-0 cursor-pointer rounded-md outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)]"
                />
                {/* pointer-events-none lets clicks fall through to the select
                    button above; elements that carry a `title` opt back in. */}
                <div className="pointer-events-none relative z-10 min-w-0">
                  <span className="flex items-center gap-2">
                    {profileSlug ? (
                      <Link
                        href={`/users/${profileSlug}`}
                        className={cn(
                          "pointer-events-auto truncate font-medium hover:text-[color:var(--aqt-teal)] hover:underline",
                          blocked && "text-[color:var(--aqt-fg-dim)]"
                        )}
                      >
                        {player.battle_tag}
                      </Link>
                    ) : (
                      <span className={cn("truncate font-medium", blocked && "text-[color:var(--aqt-fg-dim)]")}>{`#${player.id}`}</span>
                    )}
                    {blocked ? <Ban className="h-4 w-4 shrink-0 text-[color:var(--aqt-live)]" role="img" aria-label={t("unsafeOption")} /> : safetyRequired ? <ShieldCheck className="h-4 w-4 shrink-0 text-[color:var(--aqt-support)]" role="img" aria-label={t("safeOption")} /> : null}
                    <span className={cn("pointer-events-auto ml-auto shrink-0", blocked && "opacity-60")} title={divisionTitle}>
                      {division != null ? (
                        <DivisionIcon division={division} tournamentGrid={divisionGrid} width={28} height={28} className="h-7 w-7 object-contain" />
                      ) : (
                        <span className="text-[color:var(--aqt-fg-faint)]">—</span>
                      )}
                    </span>
                  </span>
                  <span className={cn("mt-1 flex flex-wrap items-center gap-1.5", blocked && "opacity-60")}>
                    {primaryRole ? (
                      <span className="pointer-events-auto inline-flex min-w-0 items-center gap-1" title={t(`roles.${primaryRole}`)}>
                        <PlayerRoleIcon role={getRoleIconName(primaryRole)} size={18} color={ROLE_ACCENT[primaryRole]} />
                        {player.sub_role && (
                          <span className="truncate text-label uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
                            {formatSubRoleLabel(player.sub_role)}
                          </span>
                        )}
                      </span>
                    ) : (
                      <span className="rounded border border-[color:var(--aqt-border-2)] px-1 text-label uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
                        {t("noRole")}
                      </span>
                    )}
                    {secondaryRoles.map((entry) => (
                      <PlayerRoleIcon key={entry} role={getRoleIconName(entry)} size={12} color="var(--aqt-fg-faint)" />
                    ))}
                    {player.is_flex && (
                      <span className="rounded border border-[color:var(--aqt-border-2)] px-1 text-label uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
                        {t("flex")}
                      </span>
                    )}
                    {heroes.length > 0 && (
                      <AvatarStack size={24} max={4} className="pointer-events-auto ml-1">
                        {heroes.map((hero) => (
                          <Avatar key={hero.slug} className="h-6 w-6" title={hero.slug}>
                            <AvatarImage src={getHeroIconUrl(hero.slug, hero.imagePath)} alt={hero.slug} />
                          </Avatar>
                        ))}
                      </AvatarStack>
                    )}
                  </span>
                  {/* Full-strength colour: this line is the only explanation of the
                      block, so it must never be dimmed with the row. */}
                  {blocked && <span className="mt-1 block text-xs text-[color:var(--aqt-live)]">{t("unsafePlayerReason")}</span>}
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="relative z-10 h-11 w-11"
                  onClick={() => onToggleShortlist(player.id)}
                  aria-pressed={bookmarked}
                  aria-label={bookmarked ? t("removeShortlist") : t("addShortlist")}
                >
                  {bookmarked ? <BookmarkCheck className="h-4 w-4 text-[color:var(--aqt-teal)]" /> : <Bookmark className="h-4 w-4" />}
                </Button>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
