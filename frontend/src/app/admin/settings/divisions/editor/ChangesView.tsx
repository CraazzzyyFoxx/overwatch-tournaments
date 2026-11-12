"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";

import { diffBands, nativeShortLabel, rankRangeLabel, type Band, type Ladder } from "./draftReducer";

/** Both coordinates of a band in one cell: "1900–1999 · GO1–GO3"; the range alone when it has no native run. */
const spanLabel = (ladder: Ladder | null, band: Band) =>
  [rankRangeLabel(band), ladder ? nativeShortLabel(ladder, band) : null].filter(Boolean).join(" · ");

export interface ChangesViewProps {
  ladder: Ladder | null;
  base: Band[];
  bands: Band[];
  baseLabel: string;
}

/**
 * The draft against the version it was created from (F12 ·3, Changes view).
 *
 * Grouped by what happened rather than listed row by row: "removed" is the one
 * that needs explaining. A division is never deleted, it is folded into a
 * neighbour, and the players in it move there.
 */
export function ChangesView({ ladder, base, bands, baseLabel }: Readonly<ChangesViewProps>) {
  const t = useTranslations("adminSettings.divisions");
  const diff = diffBands(base, bands);
  const total =
    diff.added.length + diff.removed.length + diff.moved.length + diff.renamed.length;

  if (base.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("changes.noBase")}
      </p>
    );
  }

  if (total === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("changes.identical", { base: baseLabel })}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <p className={eyebrowClass("muted")}>
        {t("changes.summary", { base: baseLabel, count: total })}
      </p>

      <Group title={t("changes.added")} count={diff.added.length}>
        {diff.added.map((band) => (
          <Row
            key={band.slug}
            right={`${band.number}. ${band.name}`}
            detail={spanLabel(ladder, band)}
          />
        ))}
      </Group>

      <Group title={t("changes.removed")} count={diff.removed.length}>
        {diff.removed.map((band) => (
          <Row
            key={band.slug}
            left={`${band.number}. ${band.name}`}
            detail={spanLabel(ladder, band)}
          />
        ))}
      </Group>

      <Group title={t("changes.moved")} count={diff.moved.length}>
        {diff.moved.map(({ before, after }) => (
          <Row
            key={after.slug}
            left={spanLabel(ladder, before)}
            right={spanLabel(ladder, after)}
            detail={after.name}
          />
        ))}
      </Group>

      <Group title={t("changes.renamed")} count={diff.renamed.length}>
        {diff.renamed.map(({ before, after }) => (
          <Row
            key={after.slug}
            left={before.name}
            right={after.name}
            detail={spanLabel(ladder, after)}
          />
        ))}
      </Group>
    </div>
  );
}

/** `count` only decides whether the group shows: the rows under the title are the count. */
function Group({
  title,
  count,
  children
}: Readonly<{ title: string; count: number; children: ReactNode }>) {
  if (count === 0) return null;
  return (
    <section className="flex flex-col gap-1">
      <h3 className="text-sm font-semibold">{title}</h3>
      <ul className="divide-y divide-border border-y border-border">{children}</ul>
    </section>
  );
}

/** One change as before → after; an added band has no before, a removed one no after. */
function Row({
  left,
  right,
  detail
}: Readonly<{ left?: string; right?: string; detail: string }>) {
  return (
    <li className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 px-3 py-2 text-sm">
      <span className="min-w-0 truncate text-muted-foreground">{left}</span>
      <span aria-hidden className="text-muted-foreground">
        &rarr;
      </span>
      <span className="min-w-0 truncate">
        {right}
        <span className="ml-2 text-xs tabular-nums text-muted-foreground">{detail}</span>
      </span>
    </li>
  );
}
