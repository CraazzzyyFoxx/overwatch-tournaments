"use client";

import { Ban, Bookmark, BookmarkCheck, Search, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Avatar, AvatarImage, AvatarStack } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/division-grid";
import { getRoleIconName } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { DraftPickOptionsResponse, DraftPlayer, DraftRole } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { formatSubRoleLabel, getHeroIconUrl, getPlayerSlug } from "@/utils/player";

import type { DraftPoolRoleFilter, DraftPoolSort } from "../_lib/draft-workspace-model";
import { playerRoles, roleTopHeroes } from "../_lib/draft-workspace-model";

const ROLE_ACCENT: Record<DraftRole, string> = {
  tank: "var(--aqt-tank)",
  dps: "var(--aqt-damage)",
  support: "var(--aqt-support)"
};

interface PlayerPoolProps {
  players: DraftPlayer[];
  totalPlayers: number;
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
}

export function PlayerPool({
  players,
  totalPlayers,
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
  divisionGrid
}: PlayerPoolProps) {
  const t = useTranslations("draftRedesign");
  return (
    <section aria-labelledby="player-pool-heading">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[color:var(--aqt-border)] pb-3">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">{t("poolCoordinate")}</p>
          <h2 id="player-pool-heading" className="mt-1 font-onest text-lg font-semibold">{t("availablePool")}</h2>
        </div>
        <span className="font-mono text-xs text-[color:var(--aqt-fg-muted)]">{players.length}/{totalPlayers}</span>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
        <label className="relative">
          <span className="sr-only">{t("searchPlayers")}</span>
          <Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-[color:var(--aqt-fg-faint)]" />
          <Input
            className="min-h-11 pl-9"
            value={query}
            onChange={(event) => onFiltersChange({ query: event.target.value })}
            placeholder={t("searchPlayers")}
          />
        </label>
        <Select value={role} onValueChange={(value) => onFiltersChange({ role: value as DraftPoolRoleFilter })}>
          <SelectTrigger className="min-h-11 w-full sm:w-36" aria-label={t("filterRole")}><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("allRoles")}</SelectItem>
            <SelectItem value="tank">{t("roles.tank")}</SelectItem>
            <SelectItem value="dps">{t("roles.dps")}</SelectItem>
            <SelectItem value="support">{t("roles.support")}</SelectItem>
          </SelectContent>
        </Select>
        <Select value={sort} onValueChange={(value) => onFiltersChange({ sort: value as DraftPoolSort })}>
          <SelectTrigger className="min-h-11 w-full sm:w-32" aria-label={t("sortPool")}><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="rank">{t("sortRank")}</SelectItem>
            <SelectItem value="name">{t("sortName")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {players.length === 0 ? (
        <div className="py-12 text-center">
          <Search className="mx-auto h-7 w-7 text-[color:var(--aqt-fg-faint)]" />
          <p className="mt-3 font-medium">{t("noFilterResults")}</p>
          <p className="mt-1 text-sm text-[color:var(--aqt-fg-muted)]">{t("noFilterResultsHint")}</p>
          <Button variant="link" className="mt-2 min-h-11" onClick={onResetFilters}>{t("resetFilters")}</Button>
        </div>
      ) : (
        <div className="mt-4 grid gap-x-5 sm:grid-cols-2">
          {players.map((player) => {
            const roles = playerRoles(player);
            const secondaryRoles = roles.filter((entry) => entry !== player.primary_role);
            const playerOptions = options?.options.filter((option) => option.player_id === player.id) ?? [];
            const safeOption = playerOptions.find((option) => option.is_safe) ?? null;
            const blocked = safetyRequired && safeOption == null;
            const bookmarked = shortlist.has(player.id);
            const isSelected = selectedPlayerId === player.id;
            const division = player.division_number ?? resolveDivisionFromRank(divisionGrid, player.rank_value);
            const divisionTitle = [
              getDivisionLabel(divisionGrid, division),
              player.rank_value ? `${player.rank_value} SR` : null
            ].filter(Boolean).join(" · ");
            const heroes = roleTopHeroes(player, player.primary_role);
            const profileSlug = player.battle_tag ? getPlayerSlug(player.battle_tag) : null;
            const selectPlayer = () => onSelect(player, safeOption?.role ?? roles[0] ?? null);
            return (
              <article
                key={player.id}
                className={cn(
                  "group grid min-h-[76px] grid-cols-[1fr_auto] items-center gap-3 border-b border-l-2 border-[color:var(--aqt-border)] py-3 pl-3",
                  isSelected && "bg-[color:var(--aqt-teal)]/10",
                  blocked && "opacity-55"
                )}
                style={{ borderLeftColor: isSelected ? ROLE_ACCENT[player.primary_role] : "transparent" }}
              >
                <div
                  role="button"
                  tabIndex={0}
                  onClick={selectPlayer}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      selectPlayer();
                    }
                  }}
                  className="min-h-11 min-w-0 cursor-pointer rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
                  aria-pressed={isSelected}
                >
                  <span className="flex items-center gap-2">
                    {profileSlug ? (
                      <Link
                        href={`/users/${profileSlug}`}
                        onClick={(event) => event.stopPropagation()}
                        onKeyDown={(event) => event.stopPropagation()}
                        className="truncate font-medium hover:text-[color:var(--aqt-teal)] hover:underline"
                      >
                        {player.battle_tag}
                      </Link>
                    ) : (
                      <span className="truncate font-medium">{`#${player.id}`}</span>
                    )}
                    {blocked ? <Ban className="h-4 w-4 shrink-0 text-[color:var(--aqt-live)]" aria-label={t("unsafeOption")} /> : safetyRequired ? <ShieldCheck className="h-4 w-4 shrink-0 text-[color:var(--aqt-support)]" aria-label={t("safeOption")} /> : null}
                    <span className="ml-auto shrink-0" title={divisionTitle}>
                      {division != null ? (
                        <PlayerDivisionIcon division={division} tournamentGrid={divisionGrid} width={26} height={26} className="h-6 w-6 object-contain" />
                      ) : (
                        <span className="text-[color:var(--aqt-fg-faint)]">—</span>
                      )}
                    </span>
                  </span>
                  <span className="mt-1 flex flex-wrap items-center gap-1.5">
                    <PlayerRoleIcon role={getRoleIconName(player.primary_role)} size={18} color={ROLE_ACCENT[player.primary_role]} />
                    {secondaryRoles.map((entry) => (
                      <PlayerRoleIcon key={entry} role={getRoleIconName(entry)} size={12} color="var(--aqt-fg-faint)" />
                    ))}
                    {player.sub_role && (
                      <span className="rounded border border-[color:var(--aqt-border-2)] px-1 text-[10px] uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
                        {formatSubRoleLabel(player.sub_role)}
                      </span>
                    )}
                    {player.is_flex && (
                      <span className="rounded border border-[color:var(--aqt-border-2)] px-1 text-[10px] uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
                        {t("flex")}
                      </span>
                    )}
                    {heroes.length > 0 && (
                      <AvatarStack size={18} max={4} className="ml-1">
                        {heroes.map((hero) => (
                          <Avatar key={hero.slug} className="h-[18px] w-[18px]" title={hero.slug}>
                            <AvatarImage src={getHeroIconUrl(hero.slug, hero.imagePath)} alt={hero.slug} />
                          </Avatar>
                        ))}
                      </AvatarStack>
                    )}
                  </span>
                  {blocked && <span className="mt-1 block text-xs text-[color:var(--aqt-live)]">{t("unsafePlayerReason")}</span>}
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-11 w-11"
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
