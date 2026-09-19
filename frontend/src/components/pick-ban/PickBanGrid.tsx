"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { Ban, Shield } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { cn } from "@/lib/utils";
import HeroImage from "@/components/hero/HeroImage";
import { normalizeRole, type AqtRoleKey } from "@/lib/player-role";
import type { PickBanEntry, PickBanEntryStatus, PickBanKind } from "@/types/tournament.types";

import {
  isEntrySelectable,
  poolRoundGroups,
  roundState,
  statusLabelKey,
  type PickBanAttributeLocks
} from "./pick-ban-model";

/** Generic catalog entry the grid needs to render one item's tile — either a
 * `MapRead` or a `Hero`, reduced to the fields both shapes carry. */
export interface PickBanItemLike {
  name: string;
  image_path?: string | null;
  role?: string;
  type?: string;
}

interface PickBanGridProps {
  kind: PickBanKind;
  pool: PickBanEntry[];
  itemsById: Record<number, PickBanItemLike | undefined>;
  selectedItemId: number | null;
  /** Whether available items can currently be selected by this viewer. */
  canSelect: boolean;
  /**
   * The server's `current_round`. Null for a flat pool, for a completed
   * sequence and for the unavailable state — never read as a mode or
   * completion signal; round mode comes from `pool[].round` via `poolRoundGroups`.
   */
  currentRound: number | null;
  /**
   * Reserve item per round position, from the session's snapshot (map kind
   * only — always empty for hero). See `pickBanReserveMap`.
   */
  slotReserves: Map<number, number>;
  /**
   * Items the side on the clock may no longer BAN, because it already banned
   * them earlier in this series (`PickBanState.repeat_banned`). Empty under
   * every no-repeat scope but `encounter_same_side` — the only one that leaves
   * them in the pool for the other side to still take — and empty on any step
   * that is not a `ban`: the ledger is ban memory, so protecting an item this
   * side already banned is legal (see `PregameRoom`).
   */
  repeatBanned: Set<number>;
  /**
   * What the attribute-uniqueness rule forbids (disabled) and what it makes
   * moot (greyed only) for the side on the clock — see `attributeLocks`.
   */
  locks: PickBanAttributeLocks;
  onSelect: (itemId: number) => void;
  /** Room-level header (back link, status, team matchup) merged into this card's top. */
  header: React.ReactNode;
}

const STATUS_BADGE_VARIANT: Record<
  PickBanEntryStatus,
  "secondary" | "destructive" | "default" | "outline"
> = {
  available: "outline",
  banned: "destructive",
  picked: "default",
  protected: "secondary",
  played: "secondary"
};

/** Hero Pool role filter display order; each code is its own `common.roles.*` key. */
const ROLE_ORDER: AqtRoleKey[] = ["tank", "damage", "support"];

/** Ties a locked round's tiles to the paragraph that explains why they are inert. */
const lockedHintId = (round: number) => `pick-ban-round-${round}-locked`;

/**
 * Why a tile is out of reach for the side on the clock. `blocked` and `repeat`
 * are clicks the server would reject — the round's attribute budget is spent
 * (`attributeLocks`), or this side already banned the item earlier in the series
 * (`PickBanState.repeat_banned`). `pointless` is a legal click that achieves
 * nothing, so it is greyed but never disabled.
 */
type PickBanTileLock = "blocked" | "pointless" | "repeat";

export function PickBanGrid({
  kind,
  pool,
  itemsById,
  selectedItemId,
  canSelect,
  currentRound,
  slotReserves,
  repeatBanned,
  locks,
  onSelect,
  header
}: Readonly<PickBanGridProps>) {
  const t = useTranslations("pickBan.room");
  const tCommon = useTranslations("common");
  const [roleFilter, setRoleFilter] = useState<AqtRoleKey | "all">("all");
  const roundGroups = poolRoundGroups(pool);
  const itemName = (itemId: number) =>
    itemsById[itemId]?.name ?? t(`${kind}.itemNumber`, { id: itemId });
  const roleOf = (itemId: number): AqtRoleKey | null =>
    normalizeRole(itemsById[itemId]?.type ?? itemsById[itemId]?.role);
  /** Only `available` entries can be locked; anything already taken is out of
   * play for its own reasons. */
  const lockOf = (entry: PickBanEntry): PickBanTileLock | null => {
    if (entry.status !== "available") return null;
    if (repeatBanned.has(entry.item_id)) return "repeat";
    const attribute = roleOf(entry.item_id);
    if (attribute == null) return null;
    if (locks.blocked.has(attribute)) return "blocked";
    if (locks.pointless.has(attribute)) return "pointless";
    return null;
  };

  const currentRoundRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    // Below `lg` the timeline stacks above the grid, so a Bo5 round-mode
    // sequence leaves the live round well under the fold — and it moves as
    // rounds resolve. Ref attached only to the "current" group, so a finished
    // sequence (also `currentRound: null`) leaves this a no-op instead of
    // yanking the reader away from the final order.
    currentRoundRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [currentRound]);

  // Role filter only applies to the Hero Pool -- maps have no role, and its
  // grid keeps rendering the full flat list/round groups unfiltered.
  const roleCounts =
    kind === "hero"
      ? pool.reduce<Record<AqtRoleKey, number>>(
          (counts, entry) => {
            const role = roleOf(entry.item_id);
            if (role) counts[role] += 1;
            return counts;
          },
          { tank: 0, damage: 0, support: 0 }
        )
      : null;
  const visibleEntries = (entries: PickBanEntry[]) =>
    kind === "hero" && roleFilter !== "all"
      ? entries.filter((entry) => roleOf(entry.item_id) === roleFilter)
      : entries;
  const poolLayoutClass =
    kind === "hero"
      ? "flex flex-wrap gap-2"
      : "grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4";

  /** `lockedRound` is the group's round when that round has not opened yet, else null. */
  const tile = (entry: PickBanEntry, lockedRound: number | null) => {
    const item = itemsById[entry.item_id];
    const lock = lockOf(entry);
    // `pointless` stays clickable — a captain may still have their own reasons.
    const selectable =
      isEntrySelectable(entry, { canSelect, currentRound }) && (lock == null || lock === "pointless");
    const selected = selectedItemId === entry.item_id;
    const dimmed = entry.status === "banned";
    const initials = itemName(entry.item_id)
      .split(/\s+/)
      .map((word) => word[0])
      .slice(0, 2)
      .join("")
      .toUpperCase();

    return (
      <button
        key={entry.id}
        type="button"
        disabled={!selectable}
        aria-pressed={selected}
        title={
          lockedRound != null
            ? t("round.locked", { n: lockedRound })
            : lock != null
              ? t(`rule.${lock}`)
              : undefined
        }
        aria-describedby={lockedRound != null ? lockedHintId(lockedRound) : undefined}
        onClick={() => onSelect(entry.item_id)}
        className={cn(
          "group relative flex flex-col overflow-hidden rounded-xl border text-left outline-none transition-shadow",
          selected
            ? "border-[color:var(--aqt-teal)] ring-2 ring-[color:var(--aqt-teal)]/45"
            : "border-[color:var(--aqt-border)]",
          selectable
            ? "cursor-pointer hover:border-[color:var(--aqt-teal)]/60 focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
            : "cursor-default",
          lockedRound != null ? "border-dashed opacity-55" : null,
          lock != null ? "opacity-55 grayscale" : null
        )}
      >
        <div className="relative h-20 w-full bg-[color:var(--aqt-card-2)] sm:h-24">
          {item?.image_path ? (
            <Image
              src={item.image_path}
              alt={item.name}
              fill
              sizes="(max-width: 640px) 50vw, (max-width: 1280px) 33vw, 25vw"
              className={cn(
                "object-cover transition-opacity",
                dimmed ? "opacity-30 grayscale" : null,
                entry.status === "played" ? "opacity-60" : null,
                lockedRound != null ? "opacity-45 saturate-50" : null
              )}
            />
          ) : (
            <span className="absolute inset-0 grid place-items-center font-onest text-lg font-semibold text-[color:var(--aqt-fg-faint)]">
              {initials}
            </span>
          )}
          {entry.action_index != null ? (
            <span className="absolute left-1.5 top-1.5 grid h-6 w-6 place-items-center rounded-md bg-black/65 text-xs font-semibold tabular-nums text-[color:var(--aqt-fg)]">
              {entry.action_index + 1}
            </span>
          ) : null}
        </div>
        <div className="flex flex-col gap-1.5 p-2.5">
          <span
            className={cn(
              "truncate text-sm font-medium",
              dimmed ? "line-through opacity-70" : null
            )}
          >
            {itemName(entry.item_id)}
          </span>
          <span className="flex flex-wrap items-center gap-1.5">
            <Badge variant={STATUS_BADGE_VARIANT[entry.status]} className="px-1.5 py-0 text-label">
              {t(statusLabelKey(entry))}
            </Badge>
            {entry.picked_by ? (
              <Badge
                variant="outline"
                className="px-1.5 py-0 text-label font-normal text-[color:var(--aqt-fg-muted)]"
              >
                {t(`by.${entry.picked_by}`)}
              </Badge>
            ) : null}
            {entry.protected_by ? (
              <Badge
                variant="outline"
                className="px-1.5 py-0 text-label font-normal text-[color:var(--aqt-fg-muted)]"
              >
                {t(`protectedBy.${entry.protected_by}`)}
              </Badge>
            ) : null}
          </span>
        </div>
      </button>
    );
  };

  /**
   * Icon-only Hero Pool tile: a bare round portrait, no name/status text on the
   * card. The hero name lives in `title`/`aria-label` instead of visible copy —
   * this tile optimizes for density, not for a status legend (the pick-order
   * list below still spells out who took what).
   *
   * A `protected` hero is NOT drawn as a taken one. It used to collapse into the
   * same crossed-out glyph every non-`available` status got, which read as
   * "banned" — the opposite of what a protect means: the hero is safe from the
   * opponent's ban and stays perfectly playable. It keeps its colour and wears
   * an amber shield instead, so the two never look alike.
   */
  const heroTile = (entry: PickBanEntry, lockedRound: number | null) => {
    const item = itemsById[entry.item_id];
    const lock = lockOf(entry);
    const selectable =
      isEntrySelectable(entry, { canSelect, currentRound }) && (lock == null || lock === "pointless");
    const selected = selectedItemId === entry.item_id;
    const shielded = entry.status === "protected";
    // Out of play for the rest of the round, whoever took it and however.
    const taken = entry.status !== "available" && !shielded;
    const name = itemName(entry.item_id);
    // Only the RULE gets to replace the name in the tooltip: a not-yet-open
    // round already explains itself through `aria-describedby` and the visible
    // hint under the group, and the name is this tile's only label.
    const ruleReason = lock != null ? t(`rule.${lock}`) : null;

    return (
      <button
        key={entry.id}
        type="button"
        disabled={!selectable}
        aria-pressed={selected}
        aria-label={`${name} — ${t(statusLabelKey(entry))}${ruleReason != null ? ` — ${ruleReason}` : ""}`}
        title={ruleReason ?? name}
        aria-describedby={lockedRound != null ? lockedHintId(lockedRound) : undefined}
        onClick={() => onSelect(entry.item_id)}
        className={cn(
          "group relative flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border p-0.5 outline-none transition-shadow",
          selected
            ? "border-[color:var(--aqt-teal)] ring-2 ring-[color:var(--aqt-teal)]/45"
            : shielded
              ? "border-[color:var(--aqt-amber)]/70"
              : "border-[color:var(--aqt-border)]",
          selectable
            ? "cursor-pointer hover:border-[color:var(--aqt-teal)]/60 focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
            : "cursor-default",
          lockedRound != null ? "border-dashed opacity-55" : null,
          lock != null ? "opacity-55 grayscale" : null
        )}
      >
        <HeroImage
          hero={{ name, image_path: item?.image_path ?? "", role: item?.role ?? "" }}
          size={38}
          className={cn(
            "transition-opacity",
            taken ? "opacity-40 grayscale" : null,
            lockedRound != null ? "opacity-45 saturate-50" : null
          )}
        />
        {taken ? (
          <span className="absolute inset-0 grid place-items-center" aria-hidden>
            <Ban className="h-[70%] w-[70%] text-[color:var(--aqt-rose)]" strokeWidth={1.25} />
          </span>
        ) : null}
        {shielded ? (
          // Corner badge, not an overlay: the portrait has to stay readable,
          // because this hero is still in the game.
          <span
            aria-hidden
            className="absolute -bottom-0.5 -left-0.5 grid h-4 w-4 place-items-center rounded-full bg-[color:var(--aqt-card)] ring-1 ring-[color:var(--aqt-amber)]/70"
          >
            <Shield className="h-2.5 w-2.5 text-[color:var(--aqt-amber)]" />
          </span>
        ) : null}
        {entry.action_index != null ? (
          <span className="absolute -right-0.5 -top-0.5 grid h-4 w-4 place-items-center rounded-full bg-black/70 text-label font-semibold tabular-nums text-[color:var(--aqt-fg)]">
            {entry.action_index + 1}
          </span>
        ) : null}
      </button>
    );
  };
  const renderTile = kind === "hero" ? heroTile : tile;

  return (
    <Card>
      <CardHeader className="flex flex-col gap-4 pb-3">
        {header}
        <div className="flex flex-row items-center justify-between gap-2 border-t border-[color:var(--aqt-border)] pt-4">
          <CardTitle className="text-base">{t(`${kind}.title`)}</CardTitle>
          {roundGroups ? (
            <Badge variant="outline" className="font-normal text-[color:var(--aqt-fg-muted)]">
              {t("round.inPlayCount", { count: roundGroups.length })}
            </Badge>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {roleCounts ? (
          <FilterChipGroup label={tCommon("filters")}>
            <FilterChip
              active={roleFilter === "all"}
              count={pool.length}
              onClick={() => setRoleFilter("all")}
            >
              {tCommon("all")}
            </FilterChip>
            {ROLE_ORDER.filter((role) => roleCounts[role] > 0).map((role) => (
              <FilterChip
                key={role}
                active={roleFilter === role}
                count={roleCounts[role]}
                onClick={() => setRoleFilter(role)}
              >
                {tCommon(`roles.${role}`)}
              </FilterChip>
            ))}
          </FilterChipGroup>
        ) : null}

        {roundGroups === null ? (
          <div className={poolLayoutClass}>
            {visibleEntries(pool).map((entry) => renderTile(entry, null))}
          </div>
        ) : (
          roundGroups.map((group) => {
            const state = roundState(group, currentRound);
            const locked = state === "upcoming";
            // Absent, not null, for a round that named no reserve — so this is
            // undefined for most rounds and the caption is skipped entirely
            // rather than rendered with nothing after it.
            const reserveItemId = slotReserves.get(group.round);
            return (
              <div
                key={group.round}
                data-pick-ban-round={group.round}
                ref={state === "current" ? currentRoundRef : undefined}
                aria-current={state === "current" ? "step" : undefined}
                className="flex flex-col gap-2"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold">
                    {t("round.label", { n: group.round })}
                  </span>
                  <Badge
                    variant={state === "current" ? "default" : "outline"}
                    className="px-1.5 py-0 text-label font-normal"
                  >
                    {state === "current"
                      ? t("round.current")
                      : state === "resolved"
                        ? t("round.resolved")
                        : t("round.upcoming")}
                  </Badge>
                </div>
                {locked ? (
                  <p
                    id={lockedHintId(group.round)}
                    className="text-xs text-[color:var(--aqt-fg-muted)]"
                  >
                    {t("round.locked", { n: group.round })}
                  </p>
                ) : null}
                {reserveItemId != null ? (
                  <p className="text-xs text-[color:var(--aqt-fg-muted)]">
                    {t("round.reserve", { item: itemName(reserveItemId) })}
                  </p>
                ) : null}
                <div className={poolLayoutClass}>
                  {visibleEntries(group.entries).map((entry) =>
                    renderTile(entry, locked ? group.round : null)
                  )}
                </div>
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}
