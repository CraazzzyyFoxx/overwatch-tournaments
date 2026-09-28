"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { Ban, History, Shield } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { cn } from "@/lib/utils";
import HeroImage from "@/components/hero/HeroImage";
import { normalizeRole, type AqtRoleKey } from "@/lib/roster/player-role";
import type { PickBanEntry, PickBanEntryStatus, PickBanKind } from "@/types/tournament.types";

import { poolRoundGroups, roundState, statusLabelKey, tileStatus } from "./pick-ban-model";

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
   * What the SERVER says the viewer may choose on the step in play
   * (`PickBanState.eligible`, narrowed to the selected target on a target
   * step), or null when they cannot act. Anything outside it is greyed and
   * inert rather than left to be discovered through a 400.
   */
  eligibleIds: Set<number> | null;
  /** The viewer's own blind draft: those tiles are marked, and a click removes them. */
  draftItemIds: ReadonlySet<number>;
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
  protected: "secondary"
};

/** Hero Pool role filter display order; each code is its own `common.roles.*` key. */
const ROLE_ORDER: AqtRoleKey[] = ["tank", "damage", "support"];

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
    const status = tileStatus(entry, { canSelect, currentRound, eligibleIds, draftItemIds });
    const selected = selectedItemId === entry.item_id || status.drafted;
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
          "group relative flex flex-col overflow-hidden rounded-xl border text-left outline-none transition-shadow",
          selected
            ? "border-[color:var(--aqt-teal)] ring-2 ring-[color:var(--aqt-teal)]/45"
            : "border-[color:var(--aqt-border)]",
          status.selectable
            ? "cursor-pointer hover:border-[color:var(--aqt-teal)]/60 focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
            : "cursor-default",
          lockedRound != null ? "border-dashed opacity-55" : null,
          status.ineligible ? "opacity-55 grayscale" : null
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
          <span className="flex flex-wrap items-center gap-1.5">
            <Badge variant={STATUS_BADGE_VARIANT[entry.status]} className="px-1.5 py-0 text-label">
              {t(statusLabelKey(entry))}
            </Badge>
            {entry.carried_from_round != null ? (
              <Badge
                variant="outline"
                data-carried-from={entry.carried_from_round}
                className="px-1.5 py-0 text-label font-normal text-[color:var(--aqt-fg-muted)]"
              >
                {t("carried.badge", { n: entry.carried_from_round })}
              </Badge>
            ) : entry.picked_by ? (
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
    const name = itemName(entry.item_id);
    // Only a RULE or an origin gets to replace the name in the tooltip: a
    // not-yet-open round already explains itself through `aria-describedby`,
    // and the name is this tile's only label.
    const note = status.ineligible
      ? t("rule.ineligible")
      : carried != null
        ? t("carried.tooltip", { n: carried })
        : null;

    return (
      <button
        key={entry.id}
        type="button"
        disabled={!status.selectable}
        aria-pressed={selected}
        aria-label={`${name} — ${t(statusLabelKey(entry))}${note != null ? ` — ${note}` : ""}`}
        title={note ?? name}
        aria-describedby={lockedRound != null ? lockedHintId(lockedRound) : undefined}
        onClick={() => onSelect(entry.item_id)}
        className={cn(
          "group relative flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border p-0.5 outline-none transition-shadow",
          selected
            ? "border-[color:var(--aqt-teal)] ring-2 ring-[color:var(--aqt-teal)]/45"
            : shielded
              ? "border-[color:var(--aqt-amber)]/70"
              : "border-[color:var(--aqt-border)]",
          status.selectable
            ? "cursor-pointer hover:border-[color:var(--aqt-teal)]/60 focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
            : "cursor-default",
          lockedRound != null ? "border-dashed opacity-55" : null,
          status.ineligible ? "opacity-55 grayscale" : null
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
