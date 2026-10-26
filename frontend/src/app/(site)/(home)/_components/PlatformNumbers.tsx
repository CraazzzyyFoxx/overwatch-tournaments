import { getTranslations } from "next-intl/server";

import { KpiFigure, type KpiKey } from "@/components/site/leaders";
import { Section } from "@/components/site/open-layout";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { getFormatter } from "@/lib/datetime/server";
import { getPublicWorkspaces } from "@/lib/site/public-data";
import statisticsService from "@/services/statistics.service";

const TITLE_ID = "home-numbers-title";

/** The six figures, in reading order: who plays, what runs, how much has been played. */
const KEYS = ["players", "tournaments", "communities", "encounters", "maps", "hours"] as const satisfies readonly KpiKey[];

const STRIP_CLASS =
  "grid grid-cols-1 gap-x-8 gap-y-5 border-y border-[color:var(--aqt-border)] py-7 sm:grid-cols-2 lg:grid-cols-3 min-[1180px]:grid-cols-6";

/**
 * The platform in six figures, across every community and all time: the
 * audience a partner reaches and the scale an organizer joins. Absent when
 * the totals cannot be read: a row of dashes would argue against the page.
 */
export async function PlatformNumbers() {
  const [t, kpi, format, overall, workspaces] = await Promise.all([
    getTranslations("home.numbers"),
    getTranslations("site.kpi"),
    getFormatter(),
    statisticsService.getOverallStatistics({ skipWorkspace: true }).catch(() => null),
    getPublicWorkspaces().catch(() => null)
  ]);
  if (!overall) return null;

  // Communities come from the public catalogue, not the tournament totals.
  const values: Partial<Record<KpiKey, number | undefined>> = {
    ...overall,
    communities: workspaces?.length
  };

  return (
    <Section labelledBy={TITLE_ID}>
      <Eyebrow as="h2" id={TITLE_ID} className="mb-3 block">
        {t("title")}
      </Eyebrow>
      <dl className={STRIP_CLASS}>
        {KEYS.map((key) => {
          const value = values[key];
          // Zero is a count; only a figure the read does not carry is left out.
          return typeof value === "number" ? (
            <KpiFigure key={key} label={kpi(key)} value={format.number(value)} />
          ) : null;
        })}
      </dl>
    </Section>
  );
}

export function PlatformNumbersSkeleton() {
  return (
    <div aria-hidden>
      <Skeleton className="mb-3 h-3 w-40" />
      <div className={STRIP_CLASS}>
        {KEYS.map((key) => (
          <div
            key={key}
            className="flex items-baseline justify-between gap-4 md:flex-col md:items-start md:gap-2"
          >
            <Skeleton className="h-8 w-24 md:h-12" />
            <Skeleton className="h-5 w-20" />
          </div>
        ))}
      </div>
    </div>
  );
}
