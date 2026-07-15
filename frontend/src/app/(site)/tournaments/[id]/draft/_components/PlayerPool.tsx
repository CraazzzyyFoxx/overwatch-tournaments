"use client";

import { Ban, Bookmark, BookmarkCheck, Search, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { getRoleIconName } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { DraftPickOptionsResponse, DraftPlayer, DraftRole } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import type { DraftPoolRoleFilter, DraftPoolSort } from "../_lib/draft-workspace-model";
import { playerRoles } from "../_lib/draft-workspace-model";

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
  /** Accepted but not yet consumed here — Task 8 wires division icons into the pool. */
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
  onResetFilters
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
            const playerOptions = options?.options.filter((option) => option.player_id === player.id) ?? [];
            const safeOption = playerOptions.find((option) => option.is_safe) ?? null;
            const blocked = safetyRequired && safeOption == null;
            const bookmarked = shortlist.has(player.id);
            return (
              <article
                key={player.id}
                className={cn(
                  "group grid min-h-[76px] grid-cols-[1fr_auto] items-center gap-3 border-b border-[color:var(--aqt-border)] py-3",
                  selectedPlayerId === player.id && "border-l-2 border-l-[color:var(--aqt-teal)] pl-3",
                  blocked && "opacity-55"
                )}
              >
                <button
                  type="button"
                  onClick={() => onSelect(player, safeOption?.role ?? roles[0] ?? null)}
                  className="min-h-11 min-w-0 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
                  aria-pressed={selectedPlayerId === player.id}
                >
                  <span className="flex items-center gap-2">
                    <span className="truncate font-medium">{player.battle_tag ?? `#${player.id}`}</span>
                    {blocked ? <Ban className="h-4 w-4 shrink-0 text-[color:var(--aqt-live)]" aria-label={t("unsafeOption")} /> : safetyRequired ? <ShieldCheck className="h-4 w-4 shrink-0 text-[color:var(--aqt-support)]" aria-label={t("safeOption")} /> : null}
                  </span>
                  <span className="mt-1 flex items-center gap-2">
                    {roles.map((entry) => (
                      <PlayerRoleIcon key={entry} role={getRoleIconName(entry)} size={15} color="currentColor" />
                    ))}
                    <span className="font-mono text-xs text-[color:var(--aqt-fg-muted)]">{player.rank_value ?? "—"}</span>
                  </span>
                  {blocked && <span className="mt-1 block text-xs text-[color:var(--aqt-live)]">{t("unsafePlayerReason")}</span>}
                </button>
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
