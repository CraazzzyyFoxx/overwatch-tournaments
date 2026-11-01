"use client";

import { useTranslations } from "next-intl";
import type { Item } from "@deadlock-api/ui-core/dist/components/index.js";

import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { Purchase } from "./model";
import { FAINT, ItemIcon, SLOT_COLOR, SLOT_ORDER, formatClock, useItems, useWidth, type Slot } from "./parts";

/** A purchase this recent (before the moment on screen) is marked as just bought. */
const ARRIVED_S = 60;

const slotOf = (item: Item | undefined): Slot | null =>
  item && (SLOT_ORDER as readonly string[]).includes(item.item_slot_type) ? (item.item_slot_type as Slot) : null;

/**
 * The inventory at one moment, as the shop lays it out: a cluster per column (weapon, vitality, spirit) in the game's
 * hue, strongest tier first, then the souls the inventory is worth and how they split across the columns.
 */
export function BuildRow({ held, t, atEnd }: Readonly<{ held: readonly Purchase[]; t: number; atEnd: boolean }>) {
  const tr = useTranslations();
  const format = useFormatter();
  const items = useItems();
  if (!items) return null;
  const groups = SLOT_ORDER.map((slot) => ({
    slot,
    purchases: held
      .filter((purchase) => slotOf(items.byId.get(purchase.itemId)) === slot)
      .sort(
        (a, b) => (items.byId.get(b.itemId)?.item_tier ?? 0) - (items.byId.get(a.itemId)?.item_tier ?? 0) || a.t - b.t
      )
  }));
  const worth = groups.map(({ slot, purchases }) => ({
    slot,
    souls: purchases.reduce((total, purchase) => total + (items.byId.get(purchase.itemId)?.cost ?? 0), 0)
  }));
  const total = worth.reduce((sum, part) => sum + part.souls, 0);
  if (held.length === 0) return <span className={FAINT}>—</span>;
  const compact = (value: number) => format.number(value, { notation: "compact", maximumFractionDigits: 1 });
  const split = worth
    .filter((part) => part.souls > 0)
    .map((part) => `${tr(`matches.deadlock.slot.${part.slot}`)} ${compact(part.souls)}`)
    .join(" · ");

  return (
    <div className="flex items-center gap-3">
      <ul className="flex items-center gap-1.5" aria-label={tr("matches.deadlock.build")}>
        {groups.map(({ slot, purchases }) =>
          purchases.length ? (
            <li
              key={slot}
              aria-label={tr(`matches.deadlock.slot.${slot}`)}
              className="flex gap-[3px] rounded-md border p-[3px]"
              style={{
                borderColor: `color-mix(in srgb, ${SLOT_COLOR[slot]} 38%, transparent)`,
                background: `color-mix(in srgb, ${SLOT_COLOR[slot]} 7%, transparent)`
              }}
            >
              {purchases.map((purchase) => (
                <ItemIcon
                  key={`${purchase.itemId}:${purchase.t}`}
                  purchase={purchase}
                  size="sm"
                  arrived={!atEnd && t - purchase.t <= ARRIVED_S}
                />
              ))}
            </li>
          ) : null
        )}
      </ul>
      {total > 0 ? (
        <div className="grid w-14 shrink-0 gap-1" title={split}>
          <span className="aqt-tnum text-caption text-[color:var(--aqt-fg-muted)]">{compact(total)}</span>
          <span aria-hidden className="flex h-[3px] gap-px overflow-hidden rounded-full">
            {worth.map((part) =>
              part.souls > 0 ? (
                <span key={part.slot} style={{ width: `${(part.souls / total) * 100}%`, background: SLOT_COLOR[part.slot] }} />
              ) : null
            )}
          </span>
          <span className="sr-only">{tr("matches.deadlock.invested", { souls: compact(total) })}</span>
        </div>
      ) : null}
    </div>
  );
}

const ICON = 30;
const GAP = 3;

/**
 * Every purchase on the match's clock: each item sits over the minute it was bought, items bought close together
 * stack upward, sold ones dim and anything after the moment on screen stays faint behind the cursor.
 */
export function BuildPath({
  purchases,
  durationS,
  t,
  atEnd
}: Readonly<{ purchases: readonly Purchase[]; durationS: number; t: number; atEnd: boolean }>) {
  const tr = useTranslations();
  const [ref, width] = useWidth<HTMLDivElement>();
  const end = Math.max(durationS, ...purchases.map((purchase) => purchase.t), 1);
  const x = (time: number) => (time / end) * width;

  const rowsRight: number[] = [];
  const placed = [...purchases]
    .sort((a, b) => a.t - b.t)
    .map((purchase) => {
      const left = Math.min(Math.max(0, x(purchase.t) - ICON / 2), Math.max(0, width - ICON));
      let row = rowsRight.findIndex((right) => right <= left - GAP);
      if (row === -1) row = rowsRight.length;
      rowsRight[row] = left + ICON;
      return { purchase, left, row };
    });
  const rows = Math.max(1, rowsRight.length);
  const ticks: number[] = [];
  for (let s = 300; s < end; s += 300) ticks.push(s);

  return (
    <div ref={ref} className="relative">
      {width > 0 ? (
        <>
          <ol className="relative m-0" style={{ height: rows * (ICON + GAP) }} aria-label={tr("matches.deadlock.panel.buildPath")}>
            {placed.map(({ purchase, left, row }) => {
              const future = !atEnd && purchase.t > t;
              const sold = purchase.soldT !== null && (atEnd || purchase.soldT <= t);
              return (
                <li
                  key={`${purchase.itemId}:${purchase.t}`}
                  className="absolute"
                  style={{ left, bottom: row * (ICON + GAP) }}
                  title={
                    purchase.soldT === null
                      ? formatClock(purchase.t)
                      : `${formatClock(purchase.t)} · ${tr("matches.deadlock.soldAt", { time: formatClock(Math.min(purchase.soldT, durationS)) })}`
                  }
                >
                  <ItemIcon purchase={purchase} state={future ? "future" : sold ? "sold" : undefined} />
                </li>
              );
            })}
          </ol>
          <div className="relative mt-1.5 h-5 border-t border-[color:var(--aqt-border-2)]">
            {ticks.map((s) => (
              <span
                key={s}
                className={cn("aqt-tnum absolute top-1 -translate-x-1/2 text-label", FAINT)}
                style={{ left: x(s) }}
              >
                {formatClock(s)}
              </span>
            ))}
          </div>
          {atEnd ? null : (
            <span
              aria-hidden
              className="pointer-events-none absolute inset-y-0 w-px bg-[color:var(--aqt-fg)]"
              style={{ left: x(t) }}
            />
          )}
        </>
      ) : (
        <div style={{ height: ICON + 26 }} />
      )}
    </div>
  );
}
