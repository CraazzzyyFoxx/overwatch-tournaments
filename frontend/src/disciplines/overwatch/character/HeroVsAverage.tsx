"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { Eyebrow } from "@/components/ui/eyebrow";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";

import { sections, type StatRow } from "./hero-stats";
import { deltaColor, formatDelta, formatStatValue } from "./utils";

/**
 * The hero's figures against every player's average on it, grouped. Each bar starts at the average (the centre line)
 * and runs right when the player does better, left when worse, whichever way the stat runs; it reaches the end at
 * twice (or none of) the average. Without a comparison (a low sample) a row keeps its figure and draws no bar.
 */
const HeroVsAverage = ({ rows, lowSampleNote }: { rows: StatRow[]; lowSampleNote: string | null }) => {
  const t = useTranslations();
  const format = useFormatter();
  const id = useId();

  if (rows.length === 0) {
    return <p className="py-6 text-center text-caption text-[color:var(--aqt-fg-dim)]">{t("users.heroes.notEnoughData")}</p>;
  }

  return (
    <div className="gap-x-10 md:columns-2">
      {sections(rows).map((section) => (
        <section
          key={section.group}
          aria-labelledby={`${id}-${section.group}`}
          className="mb-5 break-inside-avoid last:mb-0"
        >
          <Eyebrow as="h3" id={`${id}-${section.group}`} tone="dim" className="mb-1">
            {t(`users.heroes.group.${section.group}`)}
          </Eyebrow>
          <dl>
            {section.rows.map((row) => {
              const average =
                row.average == null
                  ? null
                  : t("users.heroes.card.avg", { value: formatStatValue(format, row.name, row.average) });
              return (
                <div
                  key={row.name}
                  title={average ?? undefined}
                  className="grid grid-cols-[minmax(0,1fr)_auto_4rem_2.75rem] items-center gap-x-3 border-b border-[color:var(--aqt-border)] py-2 last:border-b-0 sm:grid-cols-[minmax(8rem,1fr)_auto_minmax(4.5rem,1fr)_3rem]"
                >
                  <dt className="truncate text-caption text-[color:var(--aqt-fg-muted)]">
                    {t(row.labelKey as Parameters<typeof t>[0])}
                  </dt>
                  <dd className="aqt-tnum text-right text-body font-semibold text-[color:var(--aqt-fg)]">
                    {formatStatValue(format, row.name, row.value)}
                    {average ? <span className="sr-only">, {average}</span> : null}
                  </dd>
                  <dd
                    aria-hidden
                    className={cn("relative h-1.5 rounded-full", row.delta != null && "bg-[color:var(--aqt-card-2)]")}
                  >
                    {row.delta == null ? null : (
                      <>
                        <span
                          className={cn(
                            "absolute inset-y-0",
                            row.delta > 0 ? "left-1/2 rounded-r-full" : "right-1/2 rounded-l-full"
                          )}
                          style={{ width: `${Math.min(Math.abs(row.delta), 1) * 50}%`, background: deltaColor(row.delta) }}
                        />
                        <span className="absolute -inset-y-1 left-1/2 w-px bg-[color:var(--aqt-fg-faint)]" />
                      </>
                    )}
                  </dd>
                  <dd
                    className="aqt-tnum text-right text-label font-bold"
                    style={{ color: deltaColor(row.delta) }}
                    title={row.delta == null ? (lowSampleNote ?? undefined) : undefined}
                  >
                    {row.delta == null ? "—" : formatDelta(row.delta)}
                  </dd>
                </div>
              );
            })}
          </dl>
        </section>
      ))}
    </div>
  );
};

export default HeroVsAverage;
