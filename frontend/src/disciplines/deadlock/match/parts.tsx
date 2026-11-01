"use client";

import { createContext, useContext, useEffect, useId, useState, type CSSProperties, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { DlItemCard } from "@deadlock-api/ui-react";
import type { Item } from "@deadlock-api/ui-core/dist/components/index.js";

import Image from "@/components/ui/image";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { ColumnFormat } from "./columns";
import type { DlTeam, GameSide, Purchase, Side } from "./model";

/** A participation's colour is the in-game side it played (`theme.css`), mapped onto home/away by the view's root. */
export const SEAT: Record<Side, string> = { home: "var(--dl-home)", away: "var(--dl-away)" };
export const SEAT_TEXT: Record<Side, string> = {
  home: "text-[color:var(--dl-home)]",
  away: "text-[color:var(--dl-away)]"
};
export const GAME_SIDE_COLOR: Record<GameSide, string> = {
  hidden_king: "var(--dl-hidden-king)",
  archmother: "var(--dl-archmother)"
};

/**
 * The `--dl-home` / `--dl-away` values for two participations: the side each played, else teal and rose. Set on the
 * view's root, and again on anything portalled out of it (a tooltip), which no longer inherits them.
 */
export const sideVars = (teams: readonly [DlTeam, DlTeam]) =>
  ({
    "--dl-home": teams[0].gameSide ? GAME_SIDE_COLOR[teams[0].gameSide] : "var(--aqt-teal)",
    "--dl-away": teams[1].gameSide ? GAME_SIDE_COLOR[teams[1].gameSide] : "var(--aqt-rose)"
  }) as CSSProperties;
/** The shop's columns, left to right, and the hue the game paints each in. */
export const SLOT_ORDER = ["weapon", "vitality", "spirit"] as const;
export type Slot = (typeof SLOT_ORDER)[number];
export const SLOT_COLOR: Record<Slot, string> = {
  weapon: "var(--dl-weapon)",
  vitality: "var(--dl-vitality)",
  spirit: "var(--dl-spirit)"
};
export const FAINT = "text-[color:var(--aqt-fg-faint)]";
export const DIM = "text-[color:var(--aqt-fg-dim)]";
export const MUTED = "text-[color:var(--aqt-fg-muted)]";
export const HAIRLINE = "border-[color:var(--aqt-border)]";

export const formatClock = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export const leadingSide = (home: number, away: number): Side | null =>
  home === away ? null : home > away ? "home" : "away";

/** A figure in the scoreboard's voice: whole numbers grouped, rates as whole percents. */
export function useStatFormat() {
  const format = useFormatter();
  return (value: number, kind: ColumnFormat) =>
    kind === "pct"
      ? format.number(value, { style: "percent", maximumFractionDigits: 0 })
      : format.number(value, { maximumFractionDigits: kind === "dec" ? 1 : 0 });
}

/**
 * An element's rendered width, kept current: for layouts that pack marks in pixels. A callback ref, so an element
 * mounted after a loading state is still measured; the node is returned for reading its box.
 */
export function useWidth<T extends HTMLElement>() {
  const [node, setNode] = useState<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);
  return [setNode, width, node] as const;
}

/** The 3px seat bar a team's name or row starts with. */
export function SeatBar({ side, className }: Readonly<{ side: Side; className?: string }>) {
  return (
    <span aria-hidden className={cn("h-3.5 w-[3px] flex-none rounded-sm", className)} style={{ background: SEAT[side] }} />
  );
}

/** `h : a`, the side with less dimmed. */
export function PairScore({
  home,
  away,
  winner,
  loseClass = DIM,
  className
}: Readonly<{ home: ReactNode; away: ReactNode; winner: Side | null; loseClass?: string; className?: string }>) {
  return (
    <span className={cn("aqt-tnum inline-flex items-baseline gap-[0.4em] whitespace-nowrap", className)}>
      <span className={cn(winner === "away" && loseClass)}>{home}</span>
      <span className={FAINT}>:</span>
      <span className={cn(winner === "home" && loseClass)}>{away}</span>
    </span>
  );
}

/** An open section of a tab: a heading, an optional hint on its right, then the content. */
export function Section({ title, hint, children }: Readonly<{ title: string; hint?: string; children: ReactNode }>) {
  const id = useId();
  return (
    <section aria-labelledby={id}>
      <div className="mb-3 flex min-h-7 flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <h3 id={id} className="text-ui font-semibold">
          {title}
        </h3>
        {hint ? <span className={cn("text-caption", FAINT)}>{hint}</span> : null}
      </div>
      {children}
    </section>
  );
}

// ── Item assets ──────────────────────────────────────────────────────────────

export interface ItemAssets {
  byId: Map<number, Item>;
  byClass: Map<string, Item>;
}

/** deadlock-api's item assets of the page language; `undefined` while they load (or after they failed). */
export const ItemsContext = createContext<ItemAssets | undefined>(undefined);
export const useItems = () => useContext(ItemsContext);

const ICON_SIZE = {
  sm: "[&>dl-item-card]:size-7",
  md: "[&>dl-item-card]:size-[30px]",
  lg: "[&>dl-item-card]:size-9"
} as const;

/**
 * One purchase as deadlock-api's own item card (tooltip included). `state` dims it: `sold` once it left the inventory,
 * `future` when it is bought after the moment on screen; `arrived` marks one that just entered the inventory.
 */
export function ItemIcon({
  purchase,
  size = "md",
  state,
  arrived = false
}: Readonly<{ purchase: Purchase; size?: keyof typeof ICON_SIZE; state?: "sold" | "future"; arrived?: boolean }>) {
  const t = useTranslations();
  const items = useItems();
  const ability = purchase.imbuedAbilityId === null ? undefined : items?.byId.get(purchase.imbuedAbilityId);
  return (
    // The card's own square-size class is dropped by the React wrapper's re-renders: size the host from outside.
    <span
      className={cn(
        "relative block rounded-[3px] [&>dl-item-card]:block [&>dl-item-card]:aspect-square",
        ICON_SIZE[size],
        arrived && "ring-2 ring-[color:var(--aqt-fg)] ring-offset-1 ring-offset-[color:var(--aqt-card)] motion-safe:animate-[dl-arrive_240ms_ease-out]"
      )}
    >
      <DlItemCard itemId={purchase.itemId} itemData={items?.byId.get(purchase.itemId)} variant="icon" hoverEffect="none" />
      {/* An overlay, not ancestor opacity: that would trap the card's fixed tooltip in its stacking context. */}
      {state ? (
        <span
          aria-hidden
          className={cn(
            "pointer-events-none absolute inset-0",
            state === "sold" ? "bg-[color:var(--aqt-bg)]/60" : "bg-[color:var(--aqt-bg)]/80"
          )}
        />
      ) : null}
      {ability?.image ? (
        <Image
          src={ability.image}
          width={16}
          height={16}
          alt={t("matches.deadlock.imbuedOn", { ability: ability.name })}
          title={t("matches.deadlock.imbuedOn", { ability: ability.name })}
          className="absolute -right-1 -bottom-1 size-4 rounded-full bg-[color:var(--aqt-card)] ring-1 ring-[color:var(--aqt-border-2)]"
        />
      ) : null}
    </span>
  );
}

/** A damage source's art (an ability, an item or a weapon from the assets), or a quiet placeholder square. */
export function SourceIcon({ item }: Readonly<{ item: Item | undefined }>) {
  return item?.image ? (
    <Image src={item.image} width={20} height={20} alt="" className="size-5 shrink-0 rounded-sm" />
  ) : (
    <span aria-hidden className="size-5 shrink-0 rounded-sm bg-[color:var(--aqt-overlay-3)]" />
  );
}
