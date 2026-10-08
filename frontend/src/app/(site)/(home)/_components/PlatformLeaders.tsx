import { getTranslations } from "next-intl/server";

import {
  KpiList,
  LeaderboardColumn,
  LeadersGrid,
  type KpiKey
} from "@/components/site/leaders";
import { Column, ColumnHead, MoreLink, Section, SectionHead } from "@/components/site/open-layout";
import { Skeleton } from "@/components/ui/skeleton";
import statisticsService from "@/services/statistics.service";

import { getPublicWorkspaces } from "./home-data";

const TITLE_ID = "home-leaders-title";

const KPI_KEYS: readonly KpiKey[] = [
  "communities",
  "tournaments",
  "teams",
  "players",
  "encounters",
  "maps",
  "days",
  "hours",
  "champions"
];

/** Platform-wide totals and the two all-time leaderboards. */
export async function PlatformLeaders() {
  const t = await getTranslations("home.leaders");

  const [overall, champions, winrate, workspaces] = await Promise.all([
    statisticsService.getOverallStatistics({ skipWorkspace: true }).catch(() => null),
    statisticsService.getChampions({ skipWorkspace: true }).catch(() => null),
    statisticsService.getTopWinratePlayers({ skipWorkspace: true }).catch(() => null),
    getPublicWorkspaces().catch(() => null)
  ]);

  // "Communities" is the catalogue's own length — the statistics read counts
  // tournaments, not the communities that ran them.
  const totals = overall ? { ...overall, communities: workspaces?.length } : null;

  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead
        rubric={t("rubric")}
        title={t("title")}
        titleId={TITLE_ID}
        sub={t("sub")}
        aside={<MoreLink href="/statistics">{t("more")}</MoreLink>}
      />
      <LeadersGrid>
        <KpiList title={t("totals")} totals={totals} keys={KPI_KEYS} />
        <LeaderboardColumn
          title={t("mostWins")}
          sub={t("winsSub")}
          rows={champions ? champions.results.slice(0, 5) : null}
          value="wins"
        />
        <LeaderboardColumn
          title={t("bestWinrate")}
          sub={<span title={t("winrateTitle")}>{t("winrateSub")}</span>}
          rows={winrate ? winrate.results.slice(0, 5) : null}
          value="winrate"
        />
      </LeadersGrid>
    </Section>
  );
}

/** Three columns of rows between hairlines — the shape the data lands in. */
export function PlatformLeadersSkeleton() {
  return (
    <Section labelledBy={TITLE_ID}>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div>
          <Skeleton className="h-3 w-20" />
          <Skeleton className="mt-2 h-7 w-48" />
          <Skeleton className="mt-2 h-4 w-64" />
        </div>
        <Skeleton className="h-4 w-32" />
      </div>
      <LeadersGrid>
        {Array.from({ length: 3 }).map((_, column) => (
          <Column key={column}>
            <ColumnHead title={<Skeleton className="h-3 w-28" />} />
            {Array.from({ length: 5 }).map((_, row) => (
              <div
                key={row}
                className="flex min-h-11 items-center justify-between gap-3 border-b border-[color:var(--aqt-border)] last:border-b-0"
              >
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-4 w-10" />
              </div>
            ))}
          </Column>
        ))}
      </LeadersGrid>
    </Section>
  );
}
