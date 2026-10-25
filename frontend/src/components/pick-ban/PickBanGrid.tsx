"use client";

import Image from "@/components/ui/image";
import { useEffect, useRef, useState } from "react";
import { Ban, Check, History, Shield, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { RowButton } from "@/components/ui/row-button";
import { StatusDot } from "@/components/ui/status-dot";
import { cn } from "@/lib/utils";
import { catalogInitials } from "@/lib/catalog/initials";
import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import type { PickBanEntry, PickBanEntryStatus, PickBanKind } from "@/types/tournament.types";

import {
  characterClassOf,
  classRank,
  expiredBanIds,
  poolRoundGroups,
  roundState,
  seatName,
  statusLabelKey,
  tileStatus,
  type PickBanRoundState,
  type PickBanSeat
} from "./pick-ban-model";

/** The catalog entity (character or map) a tile renders, reduced to the fields every entity carries. */
export interface PickBanItemLike {
  name: string;
  image_path?: string | null;
  /** Catalog `attrs`: a character's class (`attrs.class`) groups it; it is never a player's role. */
  attrs?: Record<string, unknown>;
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
   * What the SERVER says the viewer may choose on the step in play
   * (`PickBanState.eligible`, narrowed to the selected target on a target
   * step), or null when they cannot act. Anything outside it is greyed and
   * inert rather than left to be discovered through a 400.
   */
  eligibleIds: Set<number> | null;
  /** The viewer's own blind draft: those tiles are marked, and a click removes them. */
  draftItemIds: ReadonlySet<number>;
  /**
   * The discipline's declared `character_classes`: the order the class filter lists them in. Classes the
   * catalog rows carry but the module does not declare follow; nothing is assumed while it is unknown.
   */
  characterClasses?: readonly string[];
  onSelect: (itemId: number) => void;
  /** The room's participations, to name who picked or protected a tile. */
  seats: PickBanSeat[];
  /** Room-level header (back link, status, team matchup) merged into this card's top. */
  header: React.ReactNode;
  /**
   * A `view-transition-name` per hero tile, for a room that animates a hero leaving the pool (the mix room names an
   * available tile so a ban or a pick can fly from it); unset, no tile is named.
   */
  itemTransitionName?: (entry: PickBanEntry) => string | undefined;
}

/** A map tile's status as coloured text: the same hue and glyph the step timeline uses per action. */
const STATUS_STYLE: Record<PickBanEntryStatus, { icon: LucideIcon | null; className: string }> = {
  available: { icon: null, className: "text-[color:var(--aqt-fg-muted)]" },
  banned: { icon: Ban, className: "text-[color:var(--aqt-rose)]" },
  picked: { icon: Check, className: "text-[color:var(--aqt-positive)]" },
  protected: { icon: Shield, className: "text-[color:var(--aqt-amber)]" }
};

/** Ties a locked round's tiles to the paragraph that explains why they are inert. */
const lockedHintId = (round: number) => `pick-ban-round-${round}-locked`;

export function PickBanGrid({
  kind,
  pool,
  itemsById,
  selectedItemId,
  canSelect,
  currentRound,
  slotReserves,
  eligibleIds,
  draftItemIds,
  onSelect,
  seats,
  header,
  characterClasses = [],
  itemTransitionName,
}: Readonly<PickBanGridProps>) {
  const t = useTranslations("pickBan.room");
  const tCommon = useTranslations("common");
  const [classFilter, setClassFilter] = useState<string | null>(null);
  const roundGroups = poolRoundGroups(pool);
  // The round whose bans bind the lobby: the one in play, or the last once
  // nothing is. Hero only — a map ban stops mattering once its slot is decided.
  const inForceRound =
    kind === "hero" && roundGroups ? (currentRound ?? roundGroups.at(-1)?.round ?? null) : null;
  const expiredBans =
    roundGroups && inForceRound != null ? expiredBanIds(roundGroups, inForceRound) : new Set<number>();
  const itemName = (itemId: number) =>
    itemsById[itemId]?.name ?? t(`${kind}.itemNumber`, { id: itemId });
  const classOf = (itemId: number) => characterClassOf(itemsById[itemId]);

  const currentRoundRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    // Below `lg` the timeline stacks above the grid, so a Bo5 round-mode
    // sequence leaves the live round well under the fold — and it moves as
    // rounds resolve. Ref attached only to the "current" group, so a finished
    // sequence (also `currentRound: null`) leaves this a no-op instead of
    // yanking the reader away from the final order.
    currentRoundRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [currentRound]);

  // Class filter only applies to the Hero Pool -- maps have no class, and its
  // grid keeps rendering the full flat list/round groups unfiltered.
  const classCounts =
    kind === "hero"
      ? pool.reduce<Map<string, number>>((counts, entry) => {
          const group = classOf(entry.item_id);
          if (group) counts.set(group, (counts.get(group) ?? 0) + 1);
          return counts;
        }, new Map())
      : null;
  const classChips = classCounts
    ? [...classCounts].sort(
        ([left], [right]) =>
          classRank(left, characterClasses) - classRank(right, characterClasses) ||
          left.localeCompare(right)
      )
    : [];
  const visibleEntries = (entries: PickBanEntry[]) =>
    kind === "hero" && classFilter !== null
      ? entries.filter((entry) => classOf(entry.item_id) === classFilter)
      : entries;
  const poolLayoutClass =
    kind === "hero"
      ? "flex flex-wrap gap-2"
      : "grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4";

  /** `lockedRound` is the group's round when that round has not opened yet, else null. */
  const tile = (entry: PickBanEntry, lockedRound: number | null) => {
    const item = itemsById[entry.item_id];
    const status = tileStatus(entry, { canSelect, currentRound, eligibleIds, draftItemIds });
    const StatusIcon = STATUS_STYLE[entry.status].icon;
    const selected = selectedItemId === entry.item_id || status.drafted;
    const dimmed = entry.status === "banned";
    const initials = catalogInitials(itemName(entry.item_id));

    return (
      <RowButton
        key={entry.id}
        disabled={!status.selectable}
        aria-pressed={selected}
        title={
          lockedRound != null
            ? t("round.locked", { n: lockedRound })
            : status.ineligible
              ? t("rule.ineligible")
              : entry.carried_from_round != null
                ? t("carried.tooltip", { n: entry.carried_from_round })
                : undefined
        }
        aria-describedby={lockedRound != null ? lockedHintId(lockedRound) : undefined}
        onClick={() => onSelect(entry.item_id)}
        className={cn(
          "group relative flex flex-col overflow-hidden rounded-xl border transition-shadow",
          selected
            ? "border-[color:var(--aqt-teal)] ring-2 ring-[color:var(--aqt-teal)]/45"
            : "border-[color:var(--aqt-border)]",
          status.selectable ? "hover:border-[color:var(--aqt-teal)]/60" : null,
          lockedRound != null ? "border-dashed opacity-55" : null,
          status.ineligible ? "opacity-55 grayscale" : null,
          // An unselectable tile reads as itself; only the states above dim it.
          lockedRound == null && !status.ineligible ? "disabled:opacity-100" : null
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
          <span className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-xs">
            <span
              className={cn(
                "inline-flex items-center gap-1 font-medium",
                STATUS_STYLE[entry.status].className
              )}
            >
              {StatusIcon ? <StatusIcon className="h-3 w-3" aria-hidden /> : null}
              {t(statusLabelKey(entry))}
            </span>
            {entry.carried_from_round != null ? (
              <span
                data-carried-from={entry.carried_from_round}
                className="inline-flex items-center gap-1 text-[color:var(--aqt-fg-muted)]"
              >
                <History className="h-3 w-3" aria-hidden />
                {t("carried.badge", { n: entry.carried_from_round })}
              </span>
            ) : entry.picked_by_kind === "team" ? (
              <span className="text-[color:var(--aqt-fg-muted)]">
                {t("by.team", { team: seatName(seats, entry.picked_by_team_id) })}
              </span>
            ) : entry.picked_by_kind === "decider" || entry.picked_by_kind === "admin" ? (
              <span className="text-[color:var(--aqt-fg-muted)]">{t(`by.${entry.picked_by_kind}`)}</span>
            ) : null}
            {entry.protected_by_kind === "team" ? (
              <span className="text-[color:var(--aqt-fg-muted)]">
                {t("protectedBy.team", { team: seatName(seats, entry.protected_by_team_id) })}
              </span>
            ) : null}
          </span>
        </div>
      </RowButton>
    );
  };

  /**
   * Icon-only Hero Pool tile: a bare round portrait, no name/status text on the
   * card. The hero name lives in `title`/`aria-label` instead of visible copy —
   * this tile optimizes for density, not for a status legend.
   *
   * A `protected` hero is NOT drawn as a taken one: the hero is safe from the
   * opponent's ban and stays perfectly playable, so it keeps its colour and
   * wears an amber shield. A ban CARRIED from an earlier map wears a clock
   * instead — nobody spent it here, and a captain hunting for who banned it
   * would otherwise find no step that did.
   */
  const heroTile = (entry: PickBanEntry, lockedRound: number | null) => {
    const item = itemsById[entry.item_id];
    const status = tileStatus(entry, { canSelect, currentRound, eligibleIds, draftItemIds });
    const selected = selectedItemId === entry.item_id || status.drafted;
    const shielded = entry.status === "protected";
    // Out of play for the rest of the round, whoever took it and however.
    const taken = entry.status !== "available" && !shielded;
    const carried = entry.carried_from_round;
    // Banned on an earlier map, and its `lifetime` no longer reaches the round in force.
    const expired = expiredBans.has(entry.id);
    const name = itemName(entry.item_id);
    // Only a RULE, an expiry or an origin gets to replace the name in the
    // tooltip: a not-yet-open round already explains itself through
    // `aria-describedby`, and the name is this tile's only label.
    const note = status.ineligible
      ? t("rule.ineligible")
      : expired
        ? t("round.banExpired")
        : carried != null
          ? t("carried.tooltip", { n: carried })
          : null;

    return (
      <RowButton
        key={entry.id}
        disabled={!status.selectable}
        aria-pressed={selected}
        aria-label={`${name} — ${t(statusLabelKey(entry))}${note != null ? ` — ${note}` : ""}`}
        title={note ?? name}
        aria-describedby={lockedRound != null ? lockedHintId(lockedRound) : undefined}
        onClick={() => onSelect(entry.item_id)}
        style={itemTransitionName ? { viewTransitionName: itemTransitionName(entry) } : undefined}
        className={cn(
          "group relative flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border p-0.5 transition-shadow",
          selected
            ? "border-[color:var(--aqt-teal)] ring-2 ring-[color:var(--aqt-teal)]/45"
            : shielded
              ? "border-[color:var(--aqt-amber)]/70"
              : "border-[color:var(--aqt-border)]",
          status.selectable ? "hover:border-[color:var(--aqt-teal)]/60" : null,
          lockedRound != null ? "border-dashed opacity-55" : null,
          status.ineligible ? "opacity-55 grayscale" : null,
          expired ? "opacity-45" : null,
          lockedRound == null && !status.ineligible && !expired ? "disabled:opacity-100" : null
        )}
      >
        {/* One frame: the tile's border carries the state; the portrait drops its own and fills the circle. */}
        <CatalogEntityImage
          entity={{ name, image_path: item?.image_path ?? null }}
          size={42}
          className={cn(
            "border-0 transition-opacity",
            taken ? "opacity-40 grayscale" : null,
            lockedRound != null ? "opacity-45 saturate-50" : null
          )}
        />
        {taken ? (
          <span className="absolute inset-0 grid place-items-center" aria-hidden>
            <Ban
              className={cn(
                "h-[70%] w-[70%]",
                expired ? "text-[color:var(--aqt-fg-faint)]" : "text-[color:var(--aqt-rose)]"
              )}
              strokeWidth={1.25}
            />
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
        {carried != null ? (
          <span
            aria-hidden
            data-carried-from={carried}
            className="absolute -bottom-0.5 -left-0.5 grid h-4 w-4 place-items-center rounded-full bg-[color:var(--aqt-card)] ring-1 ring-[color:var(--aqt-fg-faint)]/70"
          >
            <History className="h-2.5 w-2.5 text-[color:var(--aqt-fg-muted)]" />
          </span>
        ) : null}
        {entry.action_index != null ? (
          <span className="absolute -right-0.5 -top-0.5 grid h-4 w-4 place-items-center rounded-full bg-black/70 text-label font-semibold tabular-nums text-[color:var(--aqt-fg)]">
            {entry.action_index + 1}
          </span>
        ) : null}
      </RowButton>
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
            <span className="text-sm text-[color:var(--aqt-fg-muted)]">
              {t("round.inPlayCount", { count: roundGroups.length })}
            </span>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {classChips.length > 0 ? (
          <FilterChipGroup label={tCommon("filters")}>
            <FilterChip
              active={classFilter === null}
              count={pool.length}
              onClick={() => setClassFilter(null)}
            >
              {tCommon("all")}
            </FilterChip>
            {classChips.map(([code, count]) => {
              // A class code is catalog data; only a code that happens to have a localized word gets one.
              const key = `roles.${code}` as "roles.tank";
              return (
                <FilterChip
                  key={code}
                  className="capitalize"
                  active={classFilter === code}
                  count={count}
                  onClick={() => setClassFilter(code)}
                >
                  {tCommon.has(key) ? tCommon(key) : code}
                </FilterChip>
              );
            })}
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
            // How many of an earlier round's bans still bind the round in force.
            const bans =
              inForceRound != null && group.round < inForceRound
                ? visibleEntries(group.entries).filter((entry) => entry.status === "banned")
                : [];
            const activeBans = bans.filter((entry) => !expiredBans.has(entry.id)).length;
            return (
              <div
                key={group.round}
                data-pick-ban-round={group.round}
                ref={state === "current" ? currentRoundRef : undefined}
                aria-current={state === "current" ? "step" : undefined}
                className="flex flex-col gap-2"
              >
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5">
                  <PickBanRoundLabel round={group.round} state={state} />
                  {bans.length > 0 ? (
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 text-xs",
                        activeBans > 0
                          ? "text-[color:var(--aqt-rose)]"
                          : "text-[color:var(--aqt-fg-faint)]"
                      )}
                    >
                      <Ban className="h-3 w-3" aria-hidden />
                      {t("round.activeBans", { active: activeBans, total: bans.length })}
                    </span>
                  ) : null}
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

const ROUND_STATE_CLASS: Record<PickBanRoundState, string> = {
  current: "text-[color:var(--aqt-teal)]",
  resolved: "text-[color:var(--aqt-fg-muted)]",
  upcoming: "text-[color:var(--aqt-fg-muted)]"
};

/**
 * A round's heading, shared by the pool and the step timeline so both say it
 * the same way: the number, then where the round stands as coloured text — a
 * dot while it is live, a check once it is decided, nothing while it waits.
 */
export function PickBanRoundLabel({
  round,
  state
}: Readonly<{ round: number; state: PickBanRoundState }>) {
  const t = useTranslations("pickBan.room");
  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5">
      <span className="text-sm font-semibold">{t("round.label", { n: round })}</span>
      <span className={cn("inline-flex items-center gap-1.5 text-xs", ROUND_STATE_CLASS[state])}>
        {state === "current" ? <StatusDot /> : null}
        {state === "resolved" ? <Check className="h-3 w-3" aria-hidden /> : null}
        {t(`round.${state}`)}
      </span>
    </div>
  );
}
