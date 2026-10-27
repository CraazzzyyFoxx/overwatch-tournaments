import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";

import {
  Column,
  ColumnHead,
  OpenEmptyRow,
  OpenLoadError,
  Section,
  SectionHead
} from "@/components/site/open-layout";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { getFormatter } from "@/lib/datetime/server";
import { isTenantHost } from "@/lib/site/tenant-host";
import statisticsService from "@/services/statistics.service";
import type { StatRecordCode } from "@/types/statistics.types";

import { RecordContext, RecordFigure, RecordHolder } from "./records";

const TITLE_ID = "stats-records-title";

/** Read from results, so every game has them; the rest come from one game's parsed logs. */
const FEATURED: readonly StatRecordCode[] = ["win_streak", "biggest_upset", "underdog_champion", "closest_final"];

const FEATURED_GRID_CLASS = "grid grid-cols-1 gap-x-10 gap-y-8 md:grid-cols-2 xl:grid-cols-4";

function Shell({ discipline, children }: Readonly<{ discipline: string | null; children: ReactNode }>) {
  const t = useTranslations("statistics.records");
  return (
    // `#records`: the landing's leaders block links here; the section's scroll margin clears the sticky header.
    <Section id="records" labelledBy={TITLE_ID}>
      <SectionHead title={t("title")} titleId={TITLE_ID} sub={discipline ? t("subGame") : t("sub")} />
      {children}
    </Section>
  );
}

/**
 * The almanac's records: the results-based ones large, one game's log records as compact rows under them. A record
 * the server has no data for is simply not in the list.
 */
export async function RecordsSection({ discipline }: Readonly<{ discipline: string | null }>) {
  const skipWorkspace = !(await isTenantHost());
  const [t, format, data] = await Promise.all([
    getTranslations("statistics.records"),
    getFormatter(),
    statisticsService.getRecords(discipline, { skipWorkspace }).catch(() => null)
  ]);

  if (data === null) {
    return (
      <Shell discipline={discipline}>
        <OpenLoadError what={t("what")} dashed />
      </Shell>
    );
  }
  if (data.records.length === 0) {
    return (
      <Shell discipline={discipline}>
        <OpenEmptyRow>{t("empty")}</OpenEmptyRow>
      </Shell>
    );
  }

  const featured = data.records.filter((record) => FEATURED.includes(record.code));
  const fromLogs = data.records.filter((record) => !FEATURED.includes(record.code));

  return (
    <Shell discipline={discipline}>
      {featured.length > 0 ? (
        <div className={FEATURED_GRID_CLASS}>
          {featured.map((record) => (
            <article key={record.code} className="min-w-0 border-t border-[color:var(--aqt-border-3)] pt-4">
              <Eyebrow as="h3">{t(`code.${record.code}`)}</Eyebrow>
              <RecordFigure record={record} format={format} size="lg" />
              <RecordHolder record={record} className="mt-2.5 truncate text-ui font-semibold text-[color:var(--aqt-fg)]" />
              <RecordContext record={record} format={format} className="mt-1" />
            </article>
          ))}
        </div>
      ) : null}
      {fromLogs.length > 0 ? (
        <Column className={featured.length > 0 ? "mt-10" : undefined}>
          <ColumnHead title={t("fromLogs")} />
          <ul className="grid grid-cols-1 gap-x-10 md:grid-cols-2">
            {fromLogs.map((record) => (
              <li
                key={record.code}
                className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 border-b border-[color:var(--aqt-border)] py-3"
              >
                <div className="min-w-0">
                  <Eyebrow as="h4">{t(`code.${record.code}`)}</Eyebrow>
                  <RecordHolder record={record} className="mt-1 truncate text-body font-semibold text-[color:var(--aqt-fg)]" />
                  <RecordContext record={record} format={format} className="mt-0.5" />
                </div>
                <RecordFigure record={record} format={format} size="md" />
              </li>
            ))}
          </ul>
        </Column>
      ) : null}
    </Shell>
  );
}

export function RecordsSkeleton({ discipline }: Readonly<{ discipline: string | null }>) {
  return (
    <Shell discipline={discipline}>
      <div aria-hidden className={FEATURED_GRID_CLASS}>
        {FEATURED.map((code) => (
          <div key={code} className="border-t border-[color:var(--aqt-border-3)] pt-4">
            <Skeleton className="h-3 w-32" />
            <Skeleton className="mt-3 h-8 w-24" />
            <Skeleton className="mt-2.5 h-5 w-40" />
            <Skeleton className="mt-1.5 h-4 w-full max-w-56" />
          </div>
        ))}
      </div>
    </Shell>
  );
}
