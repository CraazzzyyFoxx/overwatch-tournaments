import React from "react";

import { CardTitle } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { cn } from "@/lib/utils";

/**
 * Presentational atoms and layout classes shared by the encounter detail page
 * and its `loading.tsx`. No hooks and no `"use client"`, so the server page and
 * its skeleton read the very same class strings its client panels do.
 */

/** The page's stack of sections. */
export const SURFACE = "flex flex-col gap-6 text-[color:var(--aqt-fg)]";

/**
 * The seat's hue (slot 1 teal, slot 2 rose): the page's organising contrast,
 * the same pair `TournamentTeamCardFrame slot` draws along a card's top edge.
 */
export const SIDE_TEXT = {
  1: "text-[color:var(--aqt-teal)]",
  2: "text-[color:var(--aqt-rose)]"
} as const;

/** The dim data-voice meta beside a card title or a value. */
export const CARD_SUB = "font-[family-name:var(--aqt-data)] text-label text-[color:var(--aqt-fg-dim)]";

/* The header: crumbs and actions, the board, then the series facts. Below
   `md` the board stacks, both teams reading left to right. */
export const HEADER_CARD =
  "overflow-hidden border-t-2 border-t-[color:color-mix(in_srgb,var(--aqt-teal)_55%,var(--aqt-border))]";
export const HEADER_TOP =
  "flex flex-wrap items-center justify-between gap-3 px-3.5 py-3 md:px-6 md:pb-0 md:pt-3.5";
export const BOARD =
  "grid grid-cols-1 items-center justify-items-center gap-4.5 px-3.5 py-4.5 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:justify-items-stretch md:gap-7 md:px-6 md:py-5.5";
export const BOARD_SIDE = "flex w-full min-w-0 items-center gap-3.5";
/** Slot 2 mirrors from `md`, so both logos sit beside the score and the matchup reads inward. */
export const BOARD_SIDE_TWO = "md:flex-row-reverse md:text-right";
export const BOARD_CENTER = "flex flex-col items-center gap-2.5";
export const HEADER_FOOT =
  "flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t border-[color:var(--aqt-border)] px-3.5 py-3 md:px-6 md:py-3.5";

/* One map per row. Every desktop track is fixed or `1fr`: each row is its own
   grid, so an `auto` track would size to that row and the score column would
   drift row to row. Below `md` it is two lines beside the thumbnail (which
   spans both): the map and its score, then the playtime and the controls; the
   position number is the thumbnail's order. */
export const MAP_ROW =
  "grid grid-cols-[4.5rem_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 px-3.5 py-2.5 md:grid-cols-[1.5rem_5rem_minmax(0,1fr)_4.5rem_4.5rem_10rem] md:gap-3.5 md:px-4.5";
export const MAP_INDEX = "aqt-tnum hidden text-label font-bold text-[color:var(--aqt-fg-faint)] md:block";
export const MAP_THUMB =
  "relative row-span-2 aspect-video w-18 shrink-0 overflow-hidden rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] md:row-span-1 md:w-20";
export const MAP_IDENTITY = "flex min-w-0 flex-col gap-0.75";
export const MAP_SCORE = "flex items-baseline gap-1.75 justify-self-end md:justify-self-center";
export const MAP_TIME =
  "aqt-tnum justify-self-start text-label text-[color:var(--aqt-fg-muted)] md:justify-self-end";
export const MAP_ACTION = "flex items-center justify-end gap-2";

/** A section's head: its mixed-case title, and an optional meta on the right. */
export const SECTION_HEAD = "mb-3.5 flex flex-wrap items-end justify-between gap-3";

export function SectionHead({
  title,
  meta,
  titleId
}: Readonly<{ title: React.ReactNode; meta?: React.ReactNode; titleId?: string }>) {
  return (
    <div className={SECTION_HEAD}>
      <h2 id={titleId} className="font-display text-title font-bold">
        {title}
      </h2>
      {meta != null ? <Eyebrow>{meta}</Eyebrow> : null}
    </div>
  );
}

/** A card's head row: its uppercase title, then a meta line or one status chip. */
export function CardHead({
  title,
  children
}: Readonly<{ title: React.ReactNode; children?: React.ReactNode }>) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--aqt-border)] px-4.5 py-3.5">
      <CardTitle asChild className="font-display text-body font-bold uppercase tracking-label">
        <h3>{title}</h3>
      </CardTitle>
      {children}
    </div>
  );
}

/** Hairline fact strip: label/value cells side by side, ruled between. `flush` drops the rule above it. */
export function FactGrid({
  flush = false,
  children
}: Readonly<{ flush?: boolean; children: React.ReactNode }>) {
  return (
    <div
      className={cn(
        "grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))]",
        !flush && "border-t border-[color:var(--aqt-border)]"
      )}
    >
      {children}
    </div>
  );
}

/** Label-over-value cell of a `FactGrid`. */
export function Fact({
  label,
  children,
  className
}: Readonly<{
  label: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}>) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-1.25 border-r border-[color:var(--aqt-border)] px-4.5 py-3.25 last:border-r-0",
        className
      )}
    >
      <Eyebrow>{label}</Eyebrow>
      <span className="inline-flex items-center gap-1.75 font-display text-ui font-bold tabular-nums wrap-anywhere text-[color:var(--aqt-fg)]">
        {children}
      </span>
    </div>
  );
}
