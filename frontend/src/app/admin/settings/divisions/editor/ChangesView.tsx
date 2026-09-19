"use client";

import type { ReactNode } from "react";

import { EYEBROW_CLASS } from "@/components/kit/tone";
import { cn } from "@/lib/utils";

import { bandRangeLabel, diffBands, type Band } from "./draftReducer";

export interface ChangesViewProps {
  base: Band[];
  bands: Band[];
  baseLabel: string;
}

/**
 * The draft against the version it was created from (F12 ·3, Changes view).
 *
 * Grouped by what happened rather than listed row by row: "removed" is the one
 * that needs explaining — a division is never deleted, it is folded into a
 * neighbour, and the players in it move there.
 */
export function ChangesView({ base, bands, baseLabel }: Readonly<ChangesViewProps>) {
  const diff = diffBands(base, bands);
  const total =
    diff.added.length + diff.removed.length + diff.moved.length + diff.renamed.length;

  if (base.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        This version was not created from another one, so there is nothing to compare it with.
      </p>
    );
  }

  if (total === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        The draft is identical to {baseLabel}. Cut the ladder on the left to start changing it.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <p className={cn(EYEBROW_CLASS, "font-mono")}>
        {baseLabel} &rarr; draft · {total} {total === 1 ? "change" : "changes"}
      </p>

      <Group title="Added" count={diff.added.length}>
        {diff.added.map((band) => (
          <Row
            key={band.slug}
            left="—"
            right={`${band.number}. ${band.name}`}
            detail={bandRangeLabel(band)}
          />
        ))}
      </Group>

      <Group title="Removed — merged into a neighbour" count={diff.removed.length}>
        {diff.removed.map((band) => (
          <Row
            key={band.slug}
            left={`${band.number}. ${band.name}`}
            right="—"
            detail={bandRangeLabel(band)}
          />
        ))}
      </Group>

      <Group title="Band moved" count={diff.moved.length}>
        {diff.moved.map(({ before, after }) => (
          <Row
            key={after.slug}
            left={bandRangeLabel(before)}
            right={bandRangeLabel(after)}
            detail={after.name}
          />
        ))}
      </Group>

      <Group title="Renamed" count={diff.renamed.length}>
        {diff.renamed.map(({ before, after }) => (
          <Row
            key={after.slug}
            left={before.name}
            right={after.name}
            detail={bandRangeLabel(after)}
          />
        ))}
      </Group>
    </div>
  );
}

function Group({
  title,
  count,
  children
}: Readonly<{ title: string; count: number; children: ReactNode }>) {
  if (count === 0) return null;
  return (
    <section className="flex flex-col gap-1">
      <h3 className="text-sm font-semibold">
        {title} <span className="font-mono tabular-nums text-muted-foreground">{count}</span>
      </h3>
      <ul className="divide-y divide-border rounded-xl border border-border bg-card">{children}</ul>
    </section>
  );
}

function Row({
  left,
  right,
  detail
}: Readonly<{ left: string; right: string; detail: string }>) {
  return (
    <li className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 px-3 py-2 text-sm">
      <span className="min-w-0 truncate text-muted-foreground">{left}</span>
      <span aria-hidden className="text-muted-foreground">
        &rarr;
      </span>
      <span className="min-w-0 truncate">
        {right}
        <span className="ml-2 font-mono text-xs text-muted-foreground">{detail}</span>
      </span>
    </li>
  );
}
